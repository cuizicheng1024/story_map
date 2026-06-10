from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class AgentRuntimeMetadata(TypedDict, total=False):
    person: str
    langgraph_available: bool
    used_legacy_fallback: bool
    legacy_markdown_ok: bool
    fallback: str
    error: str
    max_llm_calls: object
    tool_specs: List[Dict[str, object]]
    llm_calls_used: object
    llm_calls_limit: object
    degraded_reasons: List[str]
    execution_trace: List[str]
    tool_traces: List[Dict[str, object]]
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]


class AggregatedRuntimeMetadata(TypedDict, total=False):
    llm_calls_used: int
    llm_calls_limit: int
    degraded: bool
    degraded_reasons: List[str]
    used_legacy_fallback: bool
    execution_traces: Dict[str, List[str]]
    tool_trace_count: int
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]


class TaskFileEntry(TypedDict, total=False):
    markdown: str
    html: str
    geojson: str
    csv: str


class TaskMultiEntry(TypedDict, total=False):
    html: str
    geojson: str
    csv: str


class TaskResultSummary(TypedDict, total=False):
    ok: bool
    status: str
    people: List[str]
    results: List[Dict[str, object]]
    success_count: int
    failed_count: int
    failed_people: List[str]
    multi_html_path: str
    multi_exports: Dict[str, str]
    overlaps: List[Dict[str, object]]
    duration: str
    conclusion: str
    files: List[TaskFileEntry]
    multi: TaskMultiEntry
    meta: AggregatedRuntimeMetadata


class TaskProgressEvent(TypedDict, total=False):
    label: str
    time: str
    detail: str


class TaskQueueState(TypedDict, total=False):
    position: int
    limit: int
    active: int
    active_at_start: int
    wait: str


class TaskSnapshot(TypedDict, total=False):
    exists: bool
    ok: bool
    id: str
    text: str
    status: str
    created_at: float
    updated_at: float
    progress: List[TaskProgressEvent]
    result: Optional[TaskResultSummary]
    error: str
    queue: TaskQueueState
    debug: Dict[str, object]


class TaskListItem(TypedDict, total=False):
    id: str
    text: str
    status: str
    created_at: float
    updated_at: float
    error: str
    has_result: bool
    result_ok: bool
    people: List[str]


class TaskStorageStats(TypedDict, total=False):
    db_path: str
    db_size_bytes: int
    db_main_size_bytes: int
    db_wal_size_bytes: int
    db_shm_size_bytes: int
    task_count: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    oldest_updated_at: float
    newest_updated_at: float


class TaskStorageQueryResult(TypedDict, total=False):
    ok: bool
    limit: int
    offset: int
    status: str
    total: int
    tasks: List[TaskListItem]


class TaskStorageMaintenanceResult(TypedDict, total=False):
    ok: bool
    pruned_count: int
    vacuumed: bool
    stats: TaskStorageStats


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def normalize_agent_runtime_metadata(source: object) -> AgentRuntimeMetadata:
    runtime = dict(source or {}) if isinstance(source, dict) else {}
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
        "degraded_reasons": [str(item) for item in list(runtime.get("degraded_reasons") or [])],
        "execution_trace": [str(item) for item in list(runtime.get("execution_trace") or [])],
        "tool_traces": [dict(item) for item in list(runtime.get("tool_traces") or []) if isinstance(item, dict)],
        "memory_hits": {str(key): _safe_int(value) for key, value in dict(runtime.get("memory_hits") or {}).items() if str(key).strip()},
        "memory_misses": {
            str(key): _safe_int(value) for key, value in dict(runtime.get("memory_misses") or {}).items() if str(key).strip()
        },
    }


def normalize_aggregated_runtime_meta(source: object) -> AggregatedRuntimeMetadata:
    meta = dict(source or {}) if isinstance(source, dict) else {}
    return {
        "llm_calls_used": _safe_int(meta.get("llm_calls_used")),
        "llm_calls_limit": _safe_int(meta.get("llm_calls_limit")),
        "degraded": bool(meta.get("degraded")),
        "degraded_reasons": [str(item) for item in list(meta.get("degraded_reasons") or [])],
        "used_legacy_fallback": bool(meta.get("used_legacy_fallback")),
        "execution_traces": {
            str(person): [str(step) for step in list(trace or [])]
            for person, trace in dict(meta.get("execution_traces") or {}).items()
            if str(person).strip()
        },
        "tool_trace_count": _safe_int(meta.get("tool_trace_count")),
        "memory_hits": {str(key): _safe_int(value) for key, value in dict(meta.get("memory_hits") or {}).items() if str(key).strip()},
        "memory_misses": {
            str(key): _safe_int(value) for key, value in dict(meta.get("memory_misses") or {}).items() if str(key).strip()
        },
    }


def build_task_result_summary(
    *,
    ok: bool,
    status: str,
    people: List[str],
    results: List[Dict[str, object]],
    success_count: int,
    failed_count: int,
    failed_people: List[str],
    multi_html_path: str,
    multi_exports: Dict[str, str],
    overlaps: List[Dict[str, object]],
    duration: str,
    conclusion: str,
    files: List[TaskFileEntry],
    meta: object,
    multi: Optional[TaskMultiEntry] = None,
) -> TaskResultSummary:
    summary: TaskResultSummary = {
        "ok": bool(ok),
        "status": str(status or ""),
        "people": [str(item) for item in list(people or []) if str(item).strip()],
        "results": [dict(item) for item in list(results or []) if isinstance(item, dict)],
        "success_count": _safe_int(success_count),
        "failed_count": _safe_int(failed_count),
        "failed_people": [str(item) for item in list(failed_people or []) if str(item).strip()],
        "multi_html_path": str(multi_html_path or ""),
        "multi_exports": {str(key): str(value or "") for key, value in dict(multi_exports or {}).items() if str(key).strip()},
        "overlaps": [dict(item) for item in list(overlaps or []) if isinstance(item, dict)],
        "duration": str(duration or ""),
        "conclusion": str(conclusion or ""),
        "files": [dict(item) for item in list(files or []) if isinstance(item, dict)],
        "meta": normalize_aggregated_runtime_meta(meta),
    }
    if multi:
        summary["multi"] = dict(multi)
    return summary


def build_task_snapshot(task: object, *, debug: Optional[Dict[str, object]] = None) -> TaskSnapshot:
    data = dict(task or {}) if isinstance(task, dict) else {}
    status = str(data.get("status") or "")
    snapshot: TaskSnapshot = {
        "exists": True,
        "ok": status not in {"failed", "partial_failed"},
        "id": str(data.get("id") or ""),
        "text": str(data.get("text") or ""),
        "status": status,
        "created_at": _safe_float(data.get("created_at")),
        "updated_at": _safe_float(data.get("updated_at")),
        "progress": [dict(item) for item in list(data.get("progress") or []) if isinstance(item, dict)],
        "result": data.get("result") if isinstance(data.get("result"), dict) else data.get("result"),
        "error": str(data.get("error") or ""),
        "queue": dict(data.get("queue") or {}),
    }
    if debug is not None:
        snapshot["debug"] = dict(debug)
    return snapshot


def build_task_list_item(task: object) -> TaskListItem:
    data = dict(task or {}) if isinstance(task, dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    people = [str(item) for item in list(result.get("people") or []) if str(item).strip()] if isinstance(result, dict) else []
    return {
        "id": str(data.get("id") or ""),
        "text": str(data.get("text") or ""),
        "status": str(data.get("status") or ""),
        "created_at": _safe_float(data.get("created_at")),
        "updated_at": _safe_float(data.get("updated_at")),
        "error": str(data.get("error") or ""),
        "has_result": isinstance(result, dict),
        "result_ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "people": people,
    }


__all__ = [
    "AggregatedRuntimeMetadata",
    "AgentRuntimeMetadata",
    "TaskFileEntry",
    "TaskListItem",
    "TaskMultiEntry",
    "TaskProgressEvent",
    "TaskQueueState",
    "TaskResultSummary",
    "TaskSnapshot",
    "TaskStorageMaintenanceResult",
    "TaskStorageQueryResult",
    "TaskStorageStats",
    "build_task_list_item",
    "build_task_result_summary",
    "build_task_snapshot",
    "normalize_agent_runtime_metadata",
    "normalize_aggregated_runtime_meta",
]
