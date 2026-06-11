from __future__ import annotations

from typing import Callable, Dict, List, Optional, TypedDict

try:
    from .story_agent_state import StoryAgentState
    from .story_agent_telemetry import (
        attach_memory_access_to_trace,
        consume_memory_access,
    )
    from .story_tooling import invoke_tool
except ImportError:
    from story_agent_state import StoryAgentState
    from story_agent_telemetry import (
        attach_memory_access_to_trace,
        consume_memory_access,
    )
    from story_tooling import invoke_tool


class ToolCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        tool_traces: List[Dict[str, object]],
        llm_calls_used: int,
        original: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.tool_traces = list(tool_traces or [])
        self.llm_calls_used = int(llm_calls_used)
        self.original = original


class ToolRunResult(TypedDict):
    result: object
    tool_traces: List[Dict[str, object]]
    llm_calls_used: int
    memory_access: Dict[str, object]


def _tool_meta(func: Callable[..., object]) -> object:
    return getattr(func, "__tool__", None)


def _tool_tags(func: Callable[..., object]) -> set[str]:
    meta = _tool_meta(func)
    raw = getattr(meta, "tags", ()) if meta is not None else ()
    return {str(item).strip() for item in raw if str(item).strip()}


def _is_llm_tool(func: Callable[..., object]) -> bool:
    tags = _tool_tags(func)
    return bool({"llm", "llm_optional"} & tags)


def _check_and_consume_llm_budget(
    state: StoryAgentState,
    func: Callable[..., object],
) -> int:
    if not _is_llm_tool(func):
        return int(state.get("llm_calls_used") or 0)
    used = int(state.get("llm_calls_used") or 0)
    limit = max(0, int(state.get("llm_calls_limit") or 0))
    if used >= limit:
        raise RuntimeError(f"LLM_CALL_BUDGET_EXCEEDED:{used}/{limit}")
    return used + 1


def call_tool(
    state: StoryAgentState,
    func: Callable[..., object],
    payload: object,
    *,
    agent_step: str = "",
) -> ToolRunResult:
    tool_traces = list(state.get("tool_traces") or [])
    llm_calls_used = int(state.get("llm_calls_used") or 0)
    previous_trace_count = len(tool_traces)
    try:
        llm_calls_used = _check_and_consume_llm_budget(state, func)
        result = invoke_tool(func, payload, trace_collector=tool_traces, agent_step=agent_step)
    except Exception as exc:
        consume_memory_access(func)
        raise ToolCallError(
            str(exc),
            tool_traces=tool_traces,
            llm_calls_used=llm_calls_used,
            original=exc if isinstance(exc, Exception) else None,
        ) from exc
    memory_access = consume_memory_access(func)
    attach_memory_access_to_trace(
        tool_traces,
        previous_trace_count=previous_trace_count,
        access=memory_access,
    )
    return {
        "result": result,
        "tool_traces": tool_traces,
        "llm_calls_used": llm_calls_used,
        "memory_access": memory_access,
    }


__all__ = [
    "ToolCallError",
    "ToolRunResult",
    "call_tool",
]
