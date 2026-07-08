"""Supervisor 路由决策模块 — 管线 A 的"大脑"。

本模块定义 Supervisor 的核心决策逻辑，负责根据共享状态决定下一步路由。

关键函数：
  1. build_supervisor_update()  — 分析状态，决定 next_step（核心决策函数）
  2. _resolve_revision_step()    — 修订循环的分支策略（审校未通过时如何路由）
  3. resolve_next_step()         — 读取 state["next_step"] 返回路由目标

默认执行计划（DEFAULT_AGENT_PLAN）：
  SearchAgent 检索资料 → MapAgent 补齐古今地名 → EditorAgent 生成 Markdown → CriticAgent 评估

决策优先级（从高到低）：
  1. 没有资料 → SearchAgent
  2. 没有坐标 → GeocodeAgent（MapAgent）
  3. 没有草稿 → EditorAgent
  4. 需要重写 → EditorAgent
  5. 没有审校 → CriticAgent
  6. 审校通过 → DeliverAgent（finish_agent）
  7. 审校未通过 → 进入修订循环 _resolve_revision_step()
  8. 达到最大轮次 → DeliverAgent（强制交付）
"""

from __future__ import annotations

from typing import Callable, Optional

from .state import StoryAgentState, VALID_AGENT_STEPS, append_trace, feedback_fields, max_revisions_limit
from .runtime import build_runtime_reflection

# ── 默认执行计划 ──
# 所有 Agent 完成后的理想顺序，用于状态分析和日志输出
DEFAULT_AGENT_PLAN = [
    "SearchAgent 检索资料",
    "MapAgent 补齐古今地名",
    "EditorAgent 生成 Markdown",
    "CriticAgent 评估并给出修正建议",
]


def resolve_next_step(state: StoryAgentState) -> str:
    """读取 Supervisor 设置的 next_step 并返回路由目标。

    这是 LangGraph 条件边的路由键提取函数，由 build_supervisor_update()
    写入 next_step，由本函数读取并返回给 LangGraph 的路由表。

    Args:
        state: 共享状态

    Returns:
        str: 路由目标节点名，不在 VALID_AGENT_STEPS 中时返回 "finish_agent"
    """
    step = str(state.get("next_step") or "").strip()
    if step in VALID_AGENT_STEPS:
        return step
    return "finish_agent"


def _resolve_revision_step(state: StoryAgentState) -> tuple[str, str]:
    """修订循环的分支策略 — 当 CriticAgent 发现问题时决定下一步路由。

    这是 Supervisor 最复杂的决策函数，综合以下因素：
      - critic_feedback 的问题类型（location / timeline / 其他）
      - LLM 预算剩余（near_limit）
      - 工具调用稳定性（failed_calls / timed_out_calls）
      - 记忆缓存命中率（miss_count vs hit_count）
      - Editor 工具是否超时
      - 是否已有可用坐标（usable_place_maps）

    决策优先级（从高到低）：

    1. Editor 工具超时但有草稿 → finish_agent（直接交付）
      原因：Editor 已不可用，继续修订无意义

    2. 工具链异常（有失败/超时）：
       a. 有坐标或草稿 → editor_agent（复用现有资料修稿）
       b. 什么都没有 → search_agent（回到起点补最小资料）

    3. 问题涉及 location 或 timeline：
       a. LLM 预算紧张且有坐标 → editor_agent（基于现有坐标修）
       b. 否则 → map_agent（补坐标）

    4. LLM 预算紧张且有资料 → editor_agent（避免新检索）

    5. 缓存命中率低 → editor_agent（避免重复检索）

    6. 兜底 → search_agent（补充资料）

    Args:
        state: 共享状态

    Returns:
        tuple[str, str]: (下一步路由, 决策说明日志)
    """
    # ── 提取问题类型 ──
    fields = feedback_fields(state.get("critic_feedback") or [])

    # ── 运行时反射信息 ──
    reflection = build_runtime_reflection(state)
    llm_budget = dict(reflection.get("llm_budget") or {})
    tool_summary = dict(reflection.get("tool_summary") or {})
    memory_summary = dict(reflection.get("memory_summary") or {})

    near_limit = bool(llm_budget.get("near_limit"))
    failed_calls = int(tool_summary.get("failed_calls") or 0)
    timed_out_calls = int(tool_summary.get("timed_out_calls") or 0)
    miss_count = int(memory_summary.get("miss_count") or 0)
    hit_count = int(memory_summary.get("hit_count") or 0)

    # 是否有可用的坐标（lat 和 lng 都不为 None）
    usable_place_maps = any(
        isinstance(item, dict) and item.get("lat") is not None and item.get("lng") is not None
        for item in list(state.get("place_maps") or [])
    )

    # Editor 工具是否调用失败
    editor_call_failed = any(
        isinstance(item, dict)
        and str(item.get("agent_step") or "").strip() == "editor_agent"
        and not bool(item.get("success"))
        for item in list(state.get("tool_traces") or [])
    )

    # ── 决策 1：Editor 超时 → 直接交付 ──
    if editor_call_failed and state.get("draft_markdown"):
        return "finish_agent", "🧭 Supervisor：Editor 工具超时，直接交付当前最佳稿"

    # ── 决策 2：工具链异常 ──
    if failed_calls > 0 or timed_out_calls > 0:
        if usable_place_maps or state.get("draft_markdown"):
            return "editor_agent", "🧭 Supervisor：工具不稳定，优先复用现有资料修稿"
        return "search_agent", "🧭 Supervisor：工具链异常，回到 SearchAgent 补齐最小资料"

    # ── 决策 3：地点/时间线问题 ──
    if {"location", "timeline"} & fields:
        if near_limit and state.get("place_maps"):
            return "editor_agent", "🧭 Supervisor：预算紧张，直接基于现有地名结果修稿"
        return "map_agent", "🧭 Supervisor：优先修正地点与时间线问题"

    # ── 决策 4：LLM 预算紧张 ──
    if near_limit and state.get("search_result"):
        return "editor_agent", "🧭 Supervisor：LLM 预算紧张，先处理高置信修订"

    # ── 决策 5：缓存命中率低 → 避免重复检索 ──
    if miss_count > hit_count and state.get("search_result"):
        return "editor_agent", "🧭 Supervisor：避免重复检索，先基于现有资料修稿"

    # ── 决策 6：兜底 → 补充资料 ──
    return "search_agent", "🧭 Supervisor：回到 SearchAgent 补充资料"


def build_supervisor_update(
    state: StoryAgentState,
    *,
    emit: Optional[Callable[[str], None]] = None,
) -> StoryAgentState:
    """Supervisor 核心决策函数 — 分析共享状态并决定下一步路由。

    这是管线 A 的"大脑"，每次工作 Agent 执行完毕后都会调用此函数。
    根据状态字段的填充情况，按优先级决定下一步。

    决策流程（按优先级）：

    1. 没有 search_result          → search_agent（先检索资料）
    2. 没有 place_maps              → map_agent（补齐古今地名坐标）
    3. 没有 draft_markdown          → editor_agent（生成首稿）
    4. needs_redraft = True         → editor_agent（根据新资料重写）
    5. 没有 validation              → critic_agent（交给 Critic 审阅）
    6. validation.pass = True       → finish_agent（通过，准备交付）
    7. needs_revision = True        → _resolve_revision_step()（修订循环）
    8. revision_count >= max        → finish_agent（强制交付）

    Args:
        state: 当前共享状态
        emit:  可选日志回调（用于输出决策说明）

    Returns:
        StoryAgentState: 状态更新字典（含 next_step、execution_trace、plan）
    """
    trace = append_trace(state, "supervisor")
    plan = list(state.get("plan") or DEFAULT_AGENT_PLAN)
    next_step = "search_agent"
    validation = state.get("validation") or {}
    message = ""

    # ── 决策 1：没有资料 → 检索 ──
    if not state.get("search_result"):
        next_step = "search_agent"
        message = "🧭 Supervisor：先检索人物资料"

    # ── 决策 2：没有坐标 → 补坐标 ──
    elif "place_maps" not in state:
        next_step = "map_agent"
        message = "🧭 Supervisor：补齐古今地名与坐标"

    # ── 决策 3：没有草稿 → 写首稿 ──
    elif not state.get("draft_markdown"):
        next_step = "editor_agent"
        message = "🧭 Supervisor：生成首稿"

    # ── 决策 4：需要重写 → 根据新资料重写 ──
    elif state.get("needs_redraft"):
        next_step = "editor_agent"
        message = "🧭 Supervisor：根据最新资料重新写稿"

    # ── 决策 5：没有审校 → 交给 Critic ──
    elif not validation:
        next_step = "critic_agent"
        message = "🧭 Supervisor：交给 Critic 审阅"

    # ── 决策 6：审校通过 → 交付 ──
    elif bool(validation.get("pass")):
        next_step = "finish_agent"
        message = "🧭 Supervisor：稿件通过审阅，准备交付"

    # ── 决策 7：审校未通过 → 进入修订循环 ──
    elif state.get("needs_revision"):
        next_step, message = _resolve_revision_step(state)

    # ── 决策 8：达到最大轮次 → 强制交付 ──
    elif int(state.get("revision_count") or 0) >= max_revisions_limit(state):
        next_step = "finish_agent"
        message = "🧭 Supervisor：达到最大修订轮次，交付当前最佳稿"

    # ── 输出决策日志 ──
    if message and callable(emit):
        emit(message)

    return {
        "plan": plan,
        "next_step": next_step,
        "execution_trace": trace,
    }


__all__ = [
    "DEFAULT_AGENT_PLAN",
    "build_supervisor_update",
    "resolve_next_step",
]
