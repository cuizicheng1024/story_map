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
    watch_people_count: int
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
    public_html: str
    public_geojson: str
    public_csv: str


class TaskMultiEntry(TypedDict, total=False):
    html: str
    geojson: str
    csv: str
    public_html: str
    public_geojson: str
    public_csv: str


class TaskArchiveState(TypedDict, total=False):
    state: str
    label: str
    people: List[str]
    visible: bool
    detail: str
    updated_at: float
    index_path: str
    data_path: str


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
    archive: TaskArchiveState


class TaskProgressEvent(TypedDict, total=False):
    label: str
    time: str
    detail: str


class TaskAgentStatus(TypedDict, total=False):
    agent: str
    label: str
    status: str
    detail: str
    order: int


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
    agent_status: List[TaskAgentStatus]
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
    partial_failed_count: int
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
    reconciled: Dict[str, object]
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


def _is_usable_result_item(item: object) -> bool:
    data = dict(item or {}) if isinstance(item, dict) else {}
    if bool(data.get("homepage_refresh_failed")):
        return False
    if bool(data.get("ok")):
        return True
    return str(data.get("status") or "").strip() == "degraded"


_STATUS_LABELS = {
    "queued": ("排队中", "info"),
    "running": ("进行中", "info"),
    "completed": ("已完成", "success"),
    "partial_failed": ("部分失败", "warning"),
    "failed": ("失败", "error"),
    "interrupted": ("已中断", "warning"),
    "cancelled": ("已取消", "warning"),
    "timed_out": ("已超时", "error"),
    "ok": ("正常", "success"),
    "watch": ("需关注", "warning"),
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
    watch_people_count = _safe_int(meta.get("watch_people_count"))
    degraded_people_count = _safe_int(meta.get("degraded_people_count"))
    observed_people_count = max(runtime_people_count, watch_people_count, degraded_people_count)
    if degraded_people_count > 0:
        return build_status_info(
            "degraded",
            hint=f"{observed_people_count} 个人物中有 {degraded_people_count} 个结果或 runtime 带降级信号。",
        )
    if watch_people_count > 0:
        return build_status_info(
            "watch",
            hint=f"{observed_people_count} 个人物中有 {watch_people_count} 个 runtime 需要关注。",
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
    if code == "interrupted":
        return build_status_info(code, hint="任务因服务重启或依赖中断而暂停，可重试恢复。")
    if code == "cancelled":
        return build_status_info(code, hint="任务已被取消。")
    if code == "timed_out":
        return build_status_info(code, hint="任务超过执行时限，已自动停止。")
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


def _build_task_list_status_info(status: object, *, result: object, error: object = "") -> StatusInfo:
    base = _build_task_snapshot_status_info(status, result=result, error=error)
    code = str(status or "").strip()
    result_dict = dict(result or {}) if isinstance(result, dict) else {}
    if code != "completed" or not result_dict:
        return base
    meta = normalize_aggregated_runtime_meta(result_dict.get("meta") or {})
    meta_code = str(meta.get("status") or "").strip()
    if meta_code in {"watch", "degraded"}:
        return dict(meta.get("status_info") or {})
    return base


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
    watch_people_count = _safe_int(meta.get("watch_people_count"))
    degraded_people_count = _safe_int(meta.get("degraded_people_count"))
    if degraded_people_count <= 0 and normalized.get("degraded"):
        degraded_people_count = 1
    normalized["runtime_people_count"] = runtime_people_count
    normalized["watch_people_count"] = watch_people_count
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
    if isinstance(data.get("archive"), dict):
        archive = dict(data.get("archive") or {})
        summary["archive"] = {
            "state": str(archive.get("state") or ""),
            "label": str(archive.get("label") or ""),
            "people": [str(item) for item in list(archive.get("people") or []) if str(item).strip()],
            "visible": bool(archive.get("visible")),
            "detail": str(archive.get("detail") or ""),
            "updated_at": _safe_float(archive.get("updated_at")),
            "index_path": str(archive.get("index_path") or ""),
            "data_path": str(archive.get("data_path") or ""),
        }
    if not summary["success_count"] and summary["results"]:
        summary["success_count"] = sum(1 for item in summary["results"] if _is_usable_result_item(item))
    if not summary["failed_count"] and summary["results"]:
        summary["failed_count"] = sum(1 for item in summary["results"] if not _is_usable_result_item(item))
    if not summary["failed_people"] and summary["results"]:
        summary["failed_people"] = [
            str(item.get("person") or "").strip()
            for item in summary["results"]
            if not _is_usable_result_item(item) and str(item.get("person") or "").strip()
        ]
    if not summary["status"]:
        if summary["ok"] or (summary["success_count"] and not summary["failed_count"]):
            summary["status"] = "completed"
        elif summary["failed_count"] and summary["success_count"]:
            summary["status"] = "partial_failed"
        elif summary["failed_count"] or summary["results"]:
            summary["status"] = "failed"
    summary["status_info"] = _build_task_result_status_info(
        summary.get("status"),
        people=summary.get("people") or [],
        success_count=_safe_int(summary.get("success_count")),
        failed_count=_safe_int(summary.get("failed_count")),
        failed_people=summary.get("failed_people") or [],
    )
    return summary


_AGENT_STATUS_FLOW = [
    ("search", "Search", "识别人物/查找资料", ("理解任务", "识别任务对象", "真实性过滤", "模型调用", "档案", "命中")),
    ("geocode", "Geocode", "定位地点", ("地图", "坐标", "地点", "地名", "足迹")),
    ("editor", "Editor", "整理故事", ("生成", "写作", "Markdown", "人物页", "合并视图")),
    ("critic", "Critic", "质量检查", ("校验", "验证", "审阅", "质量", "输出结论")),
    ("deliver", "Deliver", "生成页面", ("完成", "后台归档", "发布", "同步", "首页", "知识图谱")),
]


def _build_agent_status(progress: object, task_status: str) -> List[TaskAgentStatus]:
    events = [dict(item) for item in list(progress or []) if isinstance(item, dict)]
    status = str(task_status or "").strip()
    matched_index = -1
    latest_detail_by_index: Dict[int, str] = {}
    for event in events:
        text = f"{event.get('label') or ''} {event.get('detail') or ''}"
        detail = str(event.get("detail") or event.get("label") or "").strip()
        for idx, (_agent, _name, _label, markers) in enumerate(_AGENT_STATUS_FLOW):
            if any(marker in text for marker in markers):
                matched_index = max(matched_index, idx)
                if detail:
                    latest_detail_by_index[idx] = detail

    if status == "queued":
        matched_index = max(matched_index, 0)
    elif status == "running":
        matched_index = max(matched_index, 0)
    elif status == "completed":
        matched_index = len(_AGENT_STATUS_FLOW) - 1
    elif status in {"failed", "partial_failed", "cancelled", "timed_out", "interrupted"}:
        matched_index = max(matched_index, 0)

    agent_status: List[TaskAgentStatus] = []
    terminal_failed = status in {"failed", "partial_failed", "cancelled", "timed_out", "interrupted"}
    for idx, (agent, name, label, _markers) in enumerate(_AGENT_STATUS_FLOW):
        if status == "completed" or idx < matched_index:
            item_status = "completed"
        elif idx == matched_index:
            item_status = "failed" if terminal_failed else ("running" if status in {"running", "queued"} else "pending")
        else:
            item_status = "pending"
        agent_status.append({
            "agent": agent,
            "label": label,
            "status": item_status,
            "detail": latest_detail_by_index.get(idx, ""),
            "order": idx + 1,
        })
    return agent_status


def build_task_snapshot(task: object, *, debug: Optional[Dict[str, object]] = None) -> TaskSnapshot:
    data = dict(task or {}) if isinstance(task, dict) else {}
    status = str(data.get("status") or "")
    snapshot: TaskSnapshot = {
        "exists": True,
        "ok": status not in {"failed", "partial_failed", "cancelled", "timed_out", "interrupted"},
        "id": str(data.get("id") or ""),
        "text": str(data.get("text") or ""),
        "status": status,
        "created_at": _safe_float(data.get("created_at")),
        "updated_at": _safe_float(data.get("updated_at")),
        "progress": [dict(item) for item in list(data.get("progress") or []) if isinstance(item, dict)],
        "agent_status": _build_agent_status(data.get("progress") or [], status),
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
        "result_ok": _is_usable_result_item(result) if isinstance(result, dict) else False,
        "people": people,
    }
    item["status_info"] = _build_task_list_status_info(status, result=result, error=item.get("error"))
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
