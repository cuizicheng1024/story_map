from __future__ import annotations

from typing import Callable, Optional

try:
    from .story_agent_state import StoryAgentState, VALID_AGENT_STEPS, append_trace, feedback_fields, max_revisions_limit
    from .story_agent_runtime import build_runtime_reflection
except ImportError:
    from story_agent_state import StoryAgentState, VALID_AGENT_STEPS, append_trace, feedback_fields, max_revisions_limit
    from story_agent_runtime import build_runtime_reflection


DEFAULT_AGENT_PLAN = [
    "SearchAgent 检索资料",
    "MapAgent 补齐古今地名",
    "EditorAgent 生成 Markdown",
    "CriticAgent 评估并给出修正建议",
]


def resolve_next_step(state: StoryAgentState) -> str:
    step = str(state.get("next_step") or "").strip()
    if step in VALID_AGENT_STEPS:
        return step
    return "finish_agent"


def _resolve_revision_step(state: StoryAgentState) -> tuple[str, str]:
    fields = feedback_fields(state.get("critic_feedback") or [])
    reflection = build_runtime_reflection(state)
    llm_budget = dict(reflection.get("llm_budget") or {})
    tool_summary = dict(reflection.get("tool_summary") or {})
    memory_summary = dict(reflection.get("memory_summary") or {})
    near_limit = bool(llm_budget.get("near_limit"))
    failed_calls = int(tool_summary.get("failed_calls") or 0)
    timed_out_calls = int(tool_summary.get("timed_out_calls") or 0)
    miss_count = int(memory_summary.get("miss_count") or 0)
    hit_count = int(memory_summary.get("hit_count") or 0)

    if {"location", "timeline"} & fields:
        if near_limit and state.get("place_maps"):
            return "editor_agent", "🧭 Supervisor：预算紧张，直接基于现有地名结果修稿"
        return "map_agent", "🧭 Supervisor：优先修正地点与时间线问题"
    if failed_calls > 0 or timed_out_calls > 0:
        if state.get("draft_markdown"):
            return "editor_agent", "🧭 Supervisor：工具不稳定，优先复用现有资料修稿"
        return "search_agent", "🧭 Supervisor：工具链异常，回到 SearchAgent 补齐最小资料"
    if near_limit and state.get("search_result"):
        return "editor_agent", "🧭 Supervisor：LLM 预算紧张，先处理高置信修订"
    if miss_count > hit_count and state.get("search_result"):
        return "editor_agent", "🧭 Supervisor：避免重复检索，先基于现有资料修稿"
    return "search_agent", "🧭 Supervisor：回到 SearchAgent 补充资料"


def build_supervisor_update(
    state: StoryAgentState,
    *,
    emit: Optional[Callable[[str], None]] = None,
) -> StoryAgentState:
    trace = append_trace(state, "supervisor")
    plan = list(state.get("plan") or DEFAULT_AGENT_PLAN)
    next_step = "search_agent"
    validation = state.get("validation") or {}
    message = ""
    if not state.get("search_result"):
        next_step = "search_agent"
        message = "🧭 Supervisor：先检索人物资料"
    elif "place_maps" not in state:
        next_step = "map_agent"
        message = "🧭 Supervisor：补齐古今地名与坐标"
    elif not state.get("draft_markdown"):
        next_step = "editor_agent"
        message = "🧭 Supervisor：生成首稿"
    elif state.get("needs_redraft"):
        next_step = "editor_agent"
        message = "🧭 Supervisor：根据最新资料重新写稿"
    elif not validation:
        next_step = "critic_agent"
        message = "🧭 Supervisor：交给 Critic 审阅"
    elif bool(validation.get("pass")):
        next_step = "finish_agent"
        message = "🧭 Supervisor：稿件通过审阅，准备交付"
    elif state.get("needs_revision"):
        next_step, message = _resolve_revision_step(state)
    elif int(state.get("revision_count") or 0) >= max_revisions_limit(state):
        next_step = "finish_agent"
        message = "🧭 Supervisor：达到最大修订轮次，交付当前最佳稿"
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
