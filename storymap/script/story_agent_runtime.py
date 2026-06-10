from __future__ import annotations

from typing import Dict, List, TypedDict


class StoryAgentRuntimeSnapshot(TypedDict, total=False):
    person: str
    max_llm_calls: int
    langgraph_available: bool
    tool_specs: List[Dict[str, object]]
    state: Dict[str, object]
    fallback: str
    error: str
    used_legacy_fallback: bool
    legacy_markdown_ok: bool


def _runtime_snapshot_from(source: object) -> StoryAgentRuntimeSnapshot:
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict):
        return {}
    state = runtime.get("state") if isinstance(runtime.get("state"), dict) else {}
    return {
        "person": str(runtime.get("person") or ""),
        "max_llm_calls": runtime.get("max_llm_calls"),
        "langgraph_available": bool(runtime.get("langgraph_available")),
        "tool_specs": list(runtime.get("tool_specs") or []),
        "state": dict(state or {}),
        "fallback": str(runtime.get("fallback") or ""),
        "error": str(runtime.get("error") or ""),
        "used_legacy_fallback": bool(runtime.get("used_legacy_fallback")),
        "legacy_markdown_ok": bool(runtime.get("legacy_markdown_ok")),
    }


def build_runtime_snapshot(
    person: str,
    result: object = None,
    *,
    fallback: str = "",
    error: str = "",
) -> StoryAgentRuntimeSnapshot:
    snapshot = _runtime_snapshot_from(result)
    snapshot["person"] = str(person or "")
    if isinstance(result, dict):
        state = result.get("state") if isinstance(result.get("state"), dict) else {}
        snapshot["max_llm_calls"] = result.get("max_llm_calls")
        snapshot["langgraph_available"] = bool(result.get("langgraph_available"))
        snapshot["tool_specs"] = list(result.get("tool_specs") or [])
        snapshot["state"] = dict(state or {})
    if fallback:
        snapshot["fallback"] = str(fallback)
    if error:
        snapshot["error"] = str(error)
    return snapshot


def mark_runtime_legacy_fallback(runtime: object, *, person: str, markdown: object) -> StoryAgentRuntimeSnapshot:
    snapshot = _runtime_snapshot_from(runtime)
    snapshot["person"] = str(snapshot.get("person") or person or "")
    snapshot["used_legacy_fallback"] = True
    snapshot["legacy_markdown_ok"] = bool(str(markdown or "").strip())
    return snapshot


def extract_agent_runtime_metadata(source: object) -> Dict[str, object]:
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict):
        return {}
    if "state" not in runtime and any(
        key in runtime
        for key in (
            "llm_calls_used",
            "llm_calls_limit",
            "degraded_reasons",
            "execution_trace",
            "tool_traces",
            "memory_hits",
            "memory_misses",
        )
    ):
        return {
            "person": str(runtime.get("person") or ""),
            "langgraph_available": bool(runtime.get("langgraph_available")),
            "used_legacy_fallback": bool(runtime.get("used_legacy_fallback")),
            "legacy_markdown_ok": bool(runtime.get("legacy_markdown_ok")),
            "fallback": str(runtime.get("fallback") or ""),
            "error": str(runtime.get("error") or ""),
            "max_llm_calls": runtime.get("max_llm_calls"),
            "tool_specs": list(runtime.get("tool_specs") or []),
            "llm_calls_used": runtime.get("llm_calls_used"),
            "llm_calls_limit": runtime.get("llm_calls_limit"),
            "degraded_reasons": list(runtime.get("degraded_reasons") or []),
            "execution_trace": list(runtime.get("execution_trace") or []),
            "tool_traces": list(runtime.get("tool_traces") or []),
            "memory_hits": dict(runtime.get("memory_hits") or {}),
            "memory_misses": dict(runtime.get("memory_misses") or {}),
        }
    snapshot = _runtime_snapshot_from(runtime)
    state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
    return {
        "person": str(snapshot.get("person") or ""),
        "langgraph_available": bool(snapshot.get("langgraph_available")),
        "used_legacy_fallback": bool(snapshot.get("used_legacy_fallback")),
        "legacy_markdown_ok": bool(snapshot.get("legacy_markdown_ok")),
        "fallback": str(snapshot.get("fallback") or ""),
        "error": str(snapshot.get("error") or ""),
        "max_llm_calls": snapshot.get("max_llm_calls"),
        "tool_specs": list(snapshot.get("tool_specs") or []),
        "llm_calls_used": state.get("llm_calls_used"),
        "llm_calls_limit": state.get("llm_calls_limit"),
        "degraded_reasons": list(state.get("degraded_reasons") or []),
        "execution_trace": list(state.get("execution_trace") or []),
        "tool_traces": list(state.get("tool_traces") or []),
        "memory_hits": dict(state.get("memory_hits") or {}),
        "memory_misses": dict(state.get("memory_misses") or {}),
    }


def aggregate_result_runtime_meta(results: List[Dict[str, object]]) -> Dict[str, object]:
    llm_calls_used = 0
    llm_calls_limit = 0
    degraded_reasons: List[str] = []
    execution_traces: Dict[str, List[str]] = {}
    tool_trace_count = 0
    used_legacy_fallback = False
    memory_hits: Dict[str, int] = {}
    memory_misses: Dict[str, int] = {}
    for result in results:
        runtime = extract_agent_runtime_metadata(result.get("_agent_runtime"))
        if not runtime:
            continue
        try:
            llm_calls_used += int(runtime.get("llm_calls_used") or 0)
        except Exception:
            pass
        try:
            llm_calls_limit += int(runtime.get("llm_calls_limit") or 0)
        except Exception:
            pass
        used_legacy_fallback = used_legacy_fallback or bool(runtime.get("used_legacy_fallback"))
        for item in runtime.get("degraded_reasons") or []:
            reason = str(item or "").strip()
            if reason and reason not in degraded_reasons:
                degraded_reasons.append(reason)
        person = str(result.get("person") or runtime.get("person") or "").strip()
        trace = runtime.get("execution_trace") or []
        if person and isinstance(trace, list):
            execution_traces[person] = [str(item) for item in trace]
        tool_traces = runtime.get("tool_traces") or []
        if isinstance(tool_traces, list):
            tool_trace_count += len(tool_traces)
        for bucket, count in dict(runtime.get("memory_hits") or {}).items():
            key = str(bucket or "").strip()
            if not key:
                continue
            memory_hits[key] = int(memory_hits.get(key) or 0) + int(count or 0)
        for bucket, count in dict(runtime.get("memory_misses") or {}).items():
            key = str(bucket or "").strip()
            if not key:
                continue
            memory_misses[key] = int(memory_misses.get(key) or 0) + int(count or 0)
    return {
        "llm_calls_used": llm_calls_used,
        "llm_calls_limit": llm_calls_limit,
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "used_legacy_fallback": used_legacy_fallback,
        "execution_traces": execution_traces,
        "tool_trace_count": tool_trace_count,
        "memory_hits": memory_hits,
        "memory_misses": memory_misses,
    }


__all__ = [
    "StoryAgentRuntimeSnapshot",
    "aggregate_result_runtime_meta",
    "build_runtime_snapshot",
    "extract_agent_runtime_metadata",
    "mark_runtime_legacy_fallback",
]
