"""共享状态模块 — 管线 A 的"记忆体"。

本模块定义管线 A 所有 Agent 共享的状态类型 StoryAgentState，
以及状态的创建、合并、追踪等辅助函数。

核心概念：
  - StoryAgentState 是一个 TypedDict，所有 Agent 通过它通信
  - LangGraph 自动管理状态的合并（每个节点返回部分更新）
  - Manual Runner 通过 merge_state() 手动合并

状态字段说明：
  ┌─────────────────────┬──────────┬──────────────────────────────────────┐
  │ 字段                │ 类型     │ 说明                                 │
  ├─────────────────────┼──────────┼──────────────────────────────────────┤
  │ person              │ str      │ 人物名（输入）                        │
  │ plan                │ list     │ 执行计划（Supervisor 设定）           │
  │ next_step           │ str      │ 下一步路由目标（Supervisor 设定）      │
  │ search_result       │ dict     │ 检索结果（SearchAgent 输出）          │
  │ place_maps          │ list     │ 地名映射+坐标（GeocodeAgent 输出）     │
  │ draft_markdown      │ str      │ Markdown 草稿（EditorAgent 输出）     │
  │ validation          │ dict     │ 校验结果（CriticAgent 输出）          │
  │ critic_feedback     │ list     │ 审校问题清单（CriticAgent 输出）      │
  │ revision_count      │ int      │ 当前修订轮次                         │
  │ max_revisions       │ int      │ 最大修订轮次                         │
  │ needs_revision      │ bool     │ 是否需要修订                         │
  │ needs_redraft       │ bool     │ 是否需要重写（新资料获取后）           │
  │ final_markdown      │ str      │ 最终交付 Markdown（DeliverAgent 输出）│
  │ html                │ str      │ 最终交付 HTML（DeliverAgent 渲染）     │
  │ render_error        │ str      │ HTML 渲染错误（空字符串表示成功）      │
  │ execution_trace     │ list     │ 执行路径追踪（调试用）                 │
  │ tool_traces         │ list     │ 工具调用详情（调试用）                 │
  │ llm_calls_used      │ int      │ 已消耗 LLM 调用次数                   │
  │ llm_calls_limit     │ int      │ LLM 调用上限                          │
  │ degraded_reasons    │ list     │ 降级原因列表（可观测性）               │
  │ memory_hits         │ dict     │ 记忆缓存命中统计                      │
  │ memory_misses       │ dict     │ 记忆缓存未命中统计                    │
  └─────────────────────┴──────────┴──────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


# ═══════════════════════════════════════════════════════════════════
#  类型定义
# ═══════════════════════════════════════════════════════════════════

class AgentIssue(TypedDict, total=False):
    """审校问题结构 — CriticAgent 输出的单个问题。

    Fields:
        field:      问题分类（location / timeline / identity / authenticity）
        claim:      问题描述（具体指出的错误）
        correction: 修正建议
        confidence: 置信度（0.0-1.0，>= 0.7 视为高置信问题）
        reason:     问题原因说明
    """
    field: str
    claim: str
    correction: str
    confidence: float
    reason: str


class SearchSource(TypedDict, total=False):
    """检索来源结构 — SearchAgent 输出的资料引用。

    Fields:
        source:  来源类型（baidu_baike / wikipedia / llm）
        title:   资料标题
        summary: 内容摘要
        url:     来源链接
    """
    source: str
    title: str
    summary: str
    url: str


class StoryAgentState(TypedDict, total=False):
    """管线 A 共享状态 — 所有 Agent 通过此字典通信。

    使用 total=False 表示所有字段都是可选的（TypedDict 的 Partial 模式），
    各 Agent 按需读写自己负责的字段。

    字段分类：
      输入字段：person
      编排字段：plan, next_step, needs_revision, needs_redraft,
               revision_count, max_revisions
      产出字段：search_result, place_maps, draft_markdown,
               validation, critic_feedback, final_markdown
      审计字段：execution_trace, tool_traces, llm_calls_used,
               llm_calls_limit, degraded_reasons, memory_hits, memory_misses
    """
    person: str
    plan: List[str]
    next_step: str
    search_result: Dict[str, object]
    place_maps: List[Dict[str, object]]
    draft_markdown: str
    validation: Dict[str, object]
    critic_feedback: List[AgentIssue]
    revision_count: int
    max_revisions: int
    needs_revision: bool
    needs_redraft: bool
    final_markdown: str
    html: str
    render_error: str
    execution_trace: List[str]
    tool_traces: List[Dict[str, object]]
    llm_calls_used: int
    llm_calls_limit: int
    degraded_reasons: List[str]
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]


# ── 有效 Agent 步骤集合 ──
# Supervisor 的路由目标必须在此集合中，否则兜底为 finish_agent
VALID_AGENT_STEPS = {
    "search_agent",
    "map_agent",
    "editor_agent",
    "critic_agent",
    "finish_agent",
}


# ═══════════════════════════════════════════════════════════════════
#  状态工具函数
# ═══════════════════════════════════════════════════════════════════

def append_trace(state: StoryAgentState, label: str) -> List[str]:
    """向执行追踪列表追加一个节点标签。

    用于记录管线执行路径，便于调试和审计。
    例如最终 trace 可能是：
      ["supervisor","search_agent","supervisor","map_agent","supervisor",
       "editor_agent","supervisor","critic_agent","supervisor","finish_agent"]

    Args:
        state: 共享状态
        label: 节点标签（如 "search_agent", "supervisor"）

    Returns:
        List[str]: 更新后的执行追踪列表
    """
    trace = list(state.get("execution_trace") or [])
    trace.append(label)
    return trace


def feedback_fields(feedback: List[AgentIssue]) -> set[str]:
    """从审校反馈中提取问题类型集合。

    用于 Supervisor 判断修订循环的路由方向。
    例如：{"location", "timeline"} 表示需要补坐标。

    Args:
        feedback: 审校问题列表

    Returns:
        set[str]: 问题类型集合（如 {"location", "timeline", "identity"}）
    """
    fields: set[str] = set()
    for item in feedback:
        field = str(item.get("field") or "").strip()
        if field:
            fields.add(field)
    return fields


def max_revisions_limit(state: StoryAgentState) -> int:
    """读取最大修订轮次限制。

    从 state["max_revisions"] 读取，兜底值为 1。
    当 revision_count >= 此值时，Supervisor 强制交付。

    Args:
        state: 共享状态

    Returns:
        int: 最大修订轮次（>= 0）
    """
    raw = state.get("max_revisions")
    if raw is None:
        return 1
    try:
        return max(0, int(raw))
    except Exception:
        return 1


def record_degraded_reason(current: object, reason: str) -> List[str]:
    """记录一条降级原因。

    用于可观测性：当某个 Agent 降级运行时，记录降级原因到状态中，
    最终交付时随 state 一起返回，便于排查问题。

    格式："{agent_step}:{error_message}"
    例如："search_agent:ConnectionError:..."

    Args:
        current: 当前的 degraded_reasons（list 或包含 degraded_reasons 的 dict）
        reason:  降级原因文本

    Returns:
        List[str]: 更新后的降级原因列表
    """
    if isinstance(current, dict):
        items = list(current.get("degraded_reasons") or [])
    else:
        items = list(current or [])
    reason_text = str(reason or "").strip()
    if reason_text and reason_text not in items:
        items.append(reason_text)
    return items


def create_initial_state(
    person: str,
    *,
    max_revisions: int = 5,
    llm_calls_limit: int = 0,
) -> StoryAgentState:
    """创建初始共享状态。

    管线的起点，初始化所有计数器字段和空集合字段。
    注意：search_result、place_maps、draft_markdown 等产出字段不在此初始化，
    由各 Agent 在运行时按需设置。

    Args:
        person:          人物名
        max_revisions:   最大修订轮次（默认 1）
        llm_calls_limit: LLM 调用上限（0 表示不限制）

    Returns:
        StoryAgentState: 初始状态
    """
    return {
        "person": str(person or "").strip(),
        "revision_count": 0,
        "max_revisions": max(0, int(max_revisions)),
        "needs_revision": False,
        "needs_redraft": False,
        "execution_trace": [],
        "tool_traces": [],
        "llm_calls_used": 0,
        "llm_calls_limit": max(0, int(llm_calls_limit)),
        "degraded_reasons": [],
        "memory_hits": {},
        "memory_misses": {},
    }


def merge_state(state: StoryAgentState, updates: StoryAgentState) -> StoryAgentState:
    """合并状态更新（Manual Runner 使用）。

    LangGraph 自动合并节点返回值到共享状态，但 Manual Runner 需要手动合并。
    不同类型的字段有不同合并策略：
      - dict 字段（search_result, validation, memory_*）: 直接覆盖
      - list 字段（place_maps, critic_feedback, execution_trace 等）: 直接覆盖
      - 标量字段: 直接覆盖

    Args:
        state:   当前状态
        updates: 更新字典

    Returns:
        StoryAgentState: 合并后的状态
    """
    merged = dict(state)
    for key, value in updates.items():
        # dict 类型字段：直接覆盖
        if key in {"search_result", "validation", "memory_hits", "memory_misses"} and isinstance(value, dict):
            merged[key] = dict(value)
            continue
        # list 类型字段：直接覆盖
        if key in {"place_maps", "critic_feedback", "execution_trace", "tool_traces", "degraded_reasons", "plan"}:
            merged[key] = list(value or [])
            continue
        # 标量字段：直接覆盖
        merged[key] = value
    return merged


__all__ = [
    "AgentIssue",
    "SearchSource",
    "StoryAgentState",
    "VALID_AGENT_STEPS",
    "append_trace",
    "create_initial_state",
    "feedback_fields",
    "max_revisions_limit",
    "merge_state",
    "record_degraded_reason",
]
