from __future__ import annotations

from typing import Dict, List, TypedDict


class AgentIssue(TypedDict, total=False):
    field: str
    claim: str
    correction: str
    confidence: float
    reason: str


class SearchSource(TypedDict, total=False):
    source: str
    title: str
    summary: str
    url: str


class StoryAgentState(TypedDict, total=False):
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
    execution_trace: List[str]
    tool_traces: List[Dict[str, object]]
    llm_calls_used: int
    llm_calls_limit: int
    degraded_reasons: List[str]
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]


VALID_AGENT_STEPS = {
    "search_agent",
    "map_agent",
    "editor_agent",
    "critic_agent",
    "finish_agent",
}


def append_trace(state: StoryAgentState, label: str) -> List[str]:
    trace = list(state.get("execution_trace") or [])
    trace.append(label)
    return trace


def feedback_fields(feedback: List[AgentIssue]) -> set[str]:
    fields: set[str] = set()
    for item in feedback:
        field = str(item.get("field") or "").strip()
        if field:
            fields.add(field)
    return fields


def max_revisions_limit(state: StoryAgentState) -> int:
    raw = state.get("max_revisions")
    if raw is None:
        return 1
    try:
        return max(0, int(raw))
    except Exception:
        return 1


def record_degraded_reason(current: object, reason: str) -> List[str]:
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
    max_revisions: int = 1,
    llm_calls_limit: int = 0,
) -> StoryAgentState:
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
    merged = dict(state)
    for key, value in updates.items():
        if key in {"search_result", "validation", "memory_hits", "memory_misses"} and isinstance(value, dict):
            merged[key] = dict(value)
            continue
        if key in {"place_maps", "critic_feedback", "execution_trace", "tool_traces", "degraded_reasons", "plan"}:
            merged[key] = list(value or [])
            continue
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
