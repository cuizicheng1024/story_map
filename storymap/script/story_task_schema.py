from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class StatusInfo(TypedDict, total=False):
    code: str
    label: str
    level: str
    hint: str


class AgentRuntimeMetadata(TypedDict, total=False):
    has_runtime: bool
    status: str
    status_info: StatusInfo
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
    has_runtime: bool
    status: str
    status_info: StatusInfo
    runtime_people_count: int
    degraded_people_count: int
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
    status_info: StatusInfo
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
    status_info: StatusInfo
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
    status_info: StatusInfo
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


_STATUS_LABELS = {
    "queued": ("排队中", "info"),
    "running": ("进行中", "info"),
    "completed": ("已完成", "success"),
    "partial_failed": ("部分失败", "warning"),
    "failed": ("失败", "error"),
    "ok": ("正常", "success"),
    "degraded": ("已降级", "warning"),
    "empty": ("无运行信息", "muted"),
}


def build_status_info(code: object, *, hint: object = "") -> StatusInfo:
    normalized = str(code or "").strip() or "unknown"
    label, level = _STATUS_LABELS.get(normalized, (normalized, "muted"))
    return {
        "code": normalized,
        "label": label,
        "level": level,
        "hint": str(hint or "").strip(),
    }


def _runtime_has_content(runtime: Dict[str, object]) -> bool:
    if str(runtime.get("person") or "").strip():
        return True
    if runtime.get("tool_specs") or runtime.get("execution_trace") or runtime.get("tool_traces"):
        return True
    if runtime.get("llm_calls_used") is not None or runtime.get("llm_calls_limit") is not None:
        return True
    if runtime.get("memory_hits") or runtime.get("memory_misses"):
        return True
    if runtime.get("fallback") or runtime.get("error") or runtime.get("used_legacy_fallback"):
        return True
    if runtime.get("degraded_reasons"):
        return True
    return False


def _build_runtime_status_info(runtime: Dict[str, object]) -> StatusInfo:
    has_runtime = _runtime_has_content(runtime)
    if not has_runtime:
        return build_status_info("empty", hint="本次运行未产出可用的 agent runtime。")
    degraded_reasons = [str(item) for item in list(runtime.get("degraded_reasons") or []) if str(item).strip()]
    if (
        degraded_reasons
        or str(runtime.get("error") or "").strip()
        or str(runtime.get("fallback") or "").strip()
        or bool(runtime.get("used_legacy_fallback"))
    ):
        hint_parts: List[str] = []
        if degraded_reasons:
            hint_parts.append(f"降级原因：{'、'.join(degraded_reasons[:3])}")
        elif str(runtime.get("error") or "").strip():
            hint_parts.append(str(runtime.get("error") or "").strip())
        elif str(runtime.get("fallback") or "").strip():
            hint_parts.append(str(runtime.get("fallback") or "").strip())
        elif bool(runtime.get("used_legacy_fallback")):
            hint_parts.append("已使用 legacy fallback。")
        return build_status_info("degraded", hint="；".join(hint_parts))
    return build_status_info("ok", hint="本次运行未发现降级信号。")


def _build_aggregated_runtime_status_info(meta: Dict[str, object]) -> StatusInfo:
    has_runtime = bool(meta.get("has_runtime"))
    if not has_runtime:
        return build_status_info("empty", hint="当前任务结果没有可聚合的 runtime 元数据。")
    runtime_people_count = _safe_int(meta.get("runtime_people_count"))
    degraded_people_count = _safe_int(meta.get("degraded_people_count"))
    if degraded_people_count > 0:
        return build_status_info(
            "degraded",
            hint=f"{runtime_people_count} 个人物中有 {degraded_people_count} 个 runtime 带降级信号。",
        )
    return build_status_info("ok", hint=f"{runtime_people_count} 个人物 runtime 正常。")


def _build_task_result_status_info(
    status: object,
    *,
    people: List[str],
    success_count: int,
    failed_count: int,
    failed_people: List[str],
) -> StatusInfo:
    code = str(status or "").strip()
    total = len([item for item in list(people or []) if str(item).strip()])
    if code == "partial_failed":
        failed_preview = "、".join([str(item) for item in list(failed_people or [])[:3] if str(item).strip()])
        hint = f"共 {total} 人，成功 {success_count} 人，失败 {failed_count} 人"
        if failed_preview:
            hint = f"{hint}：{failed_preview}"
        return build_status_info(code, hint=hint)
    if code == "completed":
        return build_status_info(code, hint=f"共 {total} 人，已全部生成完成。")
    if code == "failed":
        return build_status_info(code, hint=f"共 {total} 人，生成未成功。")
    return build_status_info(code)


def _build_task_snapshot_status_info(status: object, *, result: object, error: object = "") -> StatusInfo:
    code = str(status or "").strip()
    result_dict = dict(result or {}) if isinstance(result, dict) else {}
    if result_dict:
        return _build_task_result_status_info(
            code,
            people=[str(item) for item in list(result_dict.get("people") or []) if str(item).strip()],
            success_count=_safe_int(result_dict.get("success_count")),
            failed_count=_safe_int(result_dict.get("failed_count")),
            failed_people=[str(item) for item in list(result_dict.get("failed_people") or []) if str(item).strip()],
        )
    if code == "failed" and str(error or "").strip():
        return build_status_info(code, hint=str(error or "").strip())
    return build_status_info(code)


def normalize_agent_runtime_metadata(source: object) -> AgentRuntimeMetadata:
    runtime = dict(source or {}) if isinstance(source, dict) else {}
    normalized: AgentRuntimeMetadata = {
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
    normalized["has_runtime"] = _runtime_has_content(normalized)
    normalized["status_info"] = _build_runtime_status_info(normalized)
    normalized["status"] = str(normalized["status_info"].get("code") or "")
    return normalized


def normalize_aggregated_runtime_meta(source: object) -> AggregatedRuntimeMetadata:
    meta = dict(source or {}) if isinstance(source, dict) else {}
    normalized: AggregatedRuntimeMetadata = {
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
    runtime_people_count = _safe_int(meta.get("runtime_people_count"))
    if runtime_people_count <= 0:
        runtime_people_count = len(dict(normalized.get("execution_traces") or {}))
    degraded_people_count = _safe_int(meta.get("degraded_people_count"))
    if degraded_people_count <= 0 and normalized.get("degraded"):
        degraded_people_count = 1
    normalized["runtime_people_count"] = runtime_people_count
    normalized["degraded_people_count"] = degraded_people_count
    normalized["has_runtime"] = bool(
        runtime_people_count
        or normalized.get("tool_trace_count")
        or normalized.get("memory_hits")
        or normalized.get("memory_misses")
        or normalized.get("used_legacy_fallback")
        or normalized.get("degraded")
        or normalized.get("llm_calls_used")
        or normalized.get("llm_calls_limit")
    )
    normalized["status_info"] = _build_aggregated_runtime_status_info(normalized)
    normalized["status"] = str(normalized["status_info"].get("code") or "")
    return normalized


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
    summary["status_info"] = _build_task_result_status_info(
        summary.get("status"),
        people=summary.get("people") or [],
        success_count=_safe_int(summary.get("success_count")),
        failed_count=_safe_int(summary.get("failed_count")),
        failed_people=summary.get("failed_people") or [],
    )
    if multi:
        summary["multi"] = dict(multi)
    return summary


def normalize_task_result_summary(source: object) -> TaskResultSummary:
    data = dict(source or {}) if isinstance(source, dict) else {}
    summary: TaskResultSummary = {
        "ok": bool(data.get("ok")),
        "status": str(data.get("status") or ""),
        "people": [str(item) for item in list(data.get("people") or []) if str(item).strip()],
        "results": [dict(item) for item in list(data.get("results") or []) if isinstance(item, dict)],
        "success_count": _safe_int(data.get("success_count")),
        "failed_count": _safe_int(data.get("failed_count")),
        "failed_people": [str(item) for item in list(data.get("failed_people") or []) if str(item).strip()],
        "multi_html_path": str(data.get("multi_html_path") or ""),
        "multi_exports": {str(key): str(value or "") for key, value in dict(data.get("multi_exports") or {}).items() if str(key).strip()},
        "overlaps": [dict(item) for item in list(data.get("overlaps") or []) if isinstance(item, dict)],
        "duration": str(data.get("duration") or ""),
        "conclusion": str(data.get("conclusion") or ""),
        "files": [dict(item) for item in list(data.get("files") or []) if isinstance(item, dict)],
        "meta": normalize_aggregated_runtime_meta(data.get("meta") or {}),
    }
    if isinstance(data.get("multi"), dict):
        summary["multi"] = dict(data.get("multi") or {})
    if not summary["status"]:
        if summary["ok"]:
            summary["status"] = "completed"
        elif summary["failed_count"] and summary["success_count"]:
            summary["status"] = "partial_failed"
        elif summary["failed_count"] or summary["results"]:
            summary["status"] = "failed"
    if not summary["success_count"] and summary["results"]:
        summary["success_count"] = sum(1 for item in summary["results"] if bool(item.get("ok")))
    if not summary["failed_count"] and summary["results"]:
        summary["failed_count"] = sum(1 for item in summary["results"] if not bool(item.get("ok")))
    if not summary["failed_people"] and summary["results"]:
        summary["failed_people"] = [
            str(item.get("person") or "").strip()
            for item in summary["results"]
            if not bool(item.get("ok")) and str(item.get("person") or "").strip()
        ]
    summary["status_info"] = _build_task_result_status_info(
        summary.get("status"),
        people=summary.get("people") or [],
        success_count=_safe_int(summary.get("success_count")),
        failed_count=_safe_int(summary.get("failed_count")),
        failed_people=summary.get("failed_people") or [],
    )
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
        "result": normalize_task_result_summary(data.get("result")) if isinstance(data.get("result"), dict) else data.get("result"),
        "error": str(data.get("error") or ""),
        "queue": dict(data.get("queue") or {}),
    }
    snapshot["status_info"] = _build_task_snapshot_status_info(
        status,
        result=snapshot.get("result"),
        error=snapshot.get("error"),
    )
    if debug is not None:
        snapshot["debug"] = dict(debug)
    return snapshot


def build_task_list_item(task: object) -> TaskListItem:
    data = dict(task or {}) if isinstance(task, dict) else {}
    result = normalize_task_result_summary(data.get("result")) if isinstance(data.get("result"), dict) else {}
    people = [str(item) for item in list(result.get("people") or []) if str(item).strip()] if isinstance(result, dict) else []
    status = str(data.get("status") or "")
    item: TaskListItem = {
        "id": str(data.get("id") or ""),
        "text": str(data.get("text") or ""),
        "status": status,
        "created_at": _safe_float(data.get("created_at")),
        "updated_at": _safe_float(data.get("updated_at")),
        "error": str(data.get("error") or ""),
        "has_result": isinstance(result, dict),
        "result_ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "people": people,
    }
    item["status_info"] = _build_task_snapshot_status_info(status, result=result, error=item.get("error"))
    return item


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
    "StatusInfo",
    "build_status_info",
    "build_task_list_item",
    "build_task_result_summary",
    "build_task_snapshot",
    "normalize_agent_runtime_metadata",
    "normalize_aggregated_runtime_meta",
    "normalize_task_result_summary",
]
