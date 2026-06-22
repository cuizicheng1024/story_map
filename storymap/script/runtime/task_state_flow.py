import time
from concurrent.futures import Future
from typing import Callable, Dict, List, Optional, Set, Tuple


def retry_count_for_task(task: Dict[str, object]) -> int:
    return max(int(task.get("retry_count") or 0), 0)


def build_new_task(
    *,
    task_id: str,
    text: str,
    dedupe_key: str,
    now: float,
    deadline_at: float,
    timeout_seconds: int,
    retry_of: str,
    retry_count: int,
    retry_reason: str,
    trigger: str,
) -> Dict[str, object]:
    return {
        "id": task_id,
        "text": text,
        "dedupe_key": str(dedupe_key or "").strip(),
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "progress": [],
        "result": None,
        "error": "",
        "queue": {},
        "cancel_requested": False,
        "cancel_reason": "",
        "timeout_seconds": int(timeout_seconds),
        "deadline_at": float(deadline_at),
        "retry_of": str(retry_of or "").strip(),
        "retry_task_id": "",
        "retry_count": max(int(retry_count), 0),
        "retry_reason": str(retry_reason or "").strip(),
        "trigger": str(trigger or "user").strip() or "user",
        "auto_retry_pending": False,
    }


def retry_allowed_for_task(
    task: Dict[str, object],
    *,
    terminal_statuses: Set[str],
    retry_limit: int,
) -> bool:
    status = str(task.get("status") or "").strip()
    if status not in terminal_statuses or status == "completed":
        return False
    return retry_count_for_task(task) < retry_limit


def normalize_recovered_tasks(
    recovered: Dict[str, Dict[str, object]],
    *,
    now: float,
    auto_retry_interrupted: bool,
    active_statuses: Set[str],
) -> Tuple[Dict[str, Dict[str, object]], List[str]]:
    normalized: Dict[str, Dict[str, object]] = {}
    interrupted_ids: List[str] = []
    for task_id, item in recovered.items():
        task = dict(item or {})
        if str(task.get("status") or "").strip() in active_statuses:
            progress = list(task.get("progress") or [])
            progress.append(
                build_progress_event(
                    "中断",
                    detail="服务重启导致任务中断，请重新提交。",
                    now=now,
                )
            )
            task["progress"] = progress
            task["status"] = "interrupted"
            task["error"] = "服务重启导致任务中断，可重试恢复。"
            task["interrupted_at"] = now
            task["auto_retry_pending"] = bool(auto_retry_interrupted)
            task["updated_at"] = now
            interrupted_ids.append(str(task_id))
        normalized[str(task_id)] = task
    return normalized, interrupted_ids


def build_runtime_metrics_snapshot(
    *,
    tasks: Dict[str, Dict[str, object]],
    queue: Dict[str, int],
    metrics: Dict[str, float],
    now: float,
    readiness_max_pending: int,
    readiness_max_running_age_seconds: int,
    task_timeout_seconds: int,
    housekeep_min_interval_seconds: int,
    last_housekeep_report: Dict[str, object],
) -> Dict[str, object]:
    oldest_queued_age = 0.0
    oldest_running_age = 0.0
    queued = 0
    running = 0
    for task in tasks.values():
        status = str(task.get("status") or "").strip()
        created_at = float(task.get("created_at") or 0)
        age = max(0.0, now - created_at) if created_at > 0 else 0.0
        if status == "queued":
            queued += 1
            oldest_queued_age = max(oldest_queued_age, age)
        elif status == "running":
            running += 1
            oldest_running_age = max(oldest_running_age, age)
    counters = {
        key: (int(value) if float(value).is_integer() else round(float(value), 3))
        for key, value in metrics.items()
    }
    alerts: List[Dict[str, object]] = []
    if queue["pending"] > readiness_max_pending:
        alerts.append(
            {
                "code": "queue_backlog_high",
                "level": "error",
                "detail": f"当前排队任务 {queue['pending']}，超过阈值 {readiness_max_pending}。",
            }
        )
    if oldest_running_age > readiness_max_running_age_seconds:
        alerts.append(
            {
                "code": "running_task_stale",
                "level": "error",
                "detail": (
                    f"最久运行任务已执行 {round(oldest_running_age, 1)} 秒，"
                    f"超过阈值 {readiness_max_running_age_seconds} 秒。"
                ),
            }
        )
    return {
        "ok": not any(str(item.get("level") or "") == "error" for item in alerts),
        "queue": {
            **queue,
            "queued_count": queued,
            "running_count": running,
            "oldest_queued_age_seconds": round(oldest_queued_age, 3),
            "oldest_running_age_seconds": round(oldest_running_age, 3),
        },
        "limits": {
            "task_timeout_seconds": int(task_timeout_seconds),
            "readiness_max_pending": int(readiness_max_pending),
            "readiness_max_running_age_seconds": int(readiness_max_running_age_seconds),
            "housekeep_min_interval_seconds": int(housekeep_min_interval_seconds),
        },
        "counters": counters,
        "alerts": alerts,
        "housekeep": dict(last_housekeep_report),
    }


def mark_task_interrupted(
    task: Dict[str, object],
    *,
    now: float,
    detail: str,
    auto_retry_interrupted: bool,
    active_statuses: Set[str],
    progress_label: str,
) -> bool:
    status = str(task.get("status") or "").strip()
    if status not in active_statuses:
        return False
    progress = list(task.get("progress") or [])
    progress.append(build_progress_event(progress_label, detail=detail, now=now))
    task["progress"] = progress
    task["status"] = "interrupted"
    task["error"] = detail or "后台巡检发现任务状态异常，已转为中断，可重试恢复。"
    task["interrupted_at"] = now
    task["auto_retry_pending"] = bool(auto_retry_interrupted)
    task["updated_at"] = now
    return True


def collect_orphan_task_ids(
    *,
    tasks: Dict[str, Dict[str, object]],
    task_futures: Dict[str, Future[None]],
    now: float,
    active_statuses: Set[str],
    task_timeout_seconds: int,
    housekeep_min_interval_seconds: int,
) -> List[str]:
    orphan_task_ids: List[str] = []
    stale_cutoff_seconds = max(task_timeout_seconds, housekeep_min_interval_seconds * 2)
    for task_id, task in tasks.items():
        status = str(task.get("status") or "").strip()
        updated_at = max(float(task.get("updated_at") or 0.0), float(task.get("created_at") or 0.0))
        age = max(0.0, now - updated_at) if updated_at > 0 else 0.0
        future = task_futures.get(task_id)
        if status in active_statuses and (future is None or future.done()) and age >= stale_cutoff_seconds:
            orphan_task_ids.append(str(task_id))
    return orphan_task_ids


def collect_auto_retry_task_ids(
    *,
    tasks: Dict[str, Dict[str, object]],
    auto_retry: bool,
    retry_allowed: Callable[[Dict[str, object]], bool],
) -> List[str]:
    if not auto_retry:
        return []
    task_ids: List[str] = []
    for task_id, task in tasks.items():
        if str(task.get("status") or "").strip() != "interrupted":
            continue
        if not bool(task.get("auto_retry_pending")):
            continue
        if str(task.get("retry_task_id") or "").strip():
            continue
        if not retry_allowed(task):
            continue
        task_ids.append(str(task_id))
    return task_ids


def build_housekeep_skip_report(previous: Dict[str, object], *, last_ran_at: float) -> Dict[str, object]:
    return {
        **previous,
        "ok": True,
        "ran": False,
        "skipped": True,
        "ran_at": last_ran_at,
    }


def build_housekeep_report(*, now: float) -> Dict[str, object]:
    return {
        "ok": True,
        "ran": True,
        "skipped": False,
        "pruned_count": 0,
        "repaired_interrupted_count": 0,
        "auto_retried_count": 0,
        "orphan_task_ids": [],
        "ran_at": now,
    }


def build_progress_event(label: str, *, detail: str = "", now: Optional[float] = None) -> Dict[str, str]:
    event = {
        "label": str(label or "").strip(),
        "time": time.strftime("%H:%M:%S", time.localtime(float(now if now is not None else time.time()))),
    }
    clean_detail = sanitize_progress_detail(detail)
    if clean_detail:
        event["detail"] = clean_detail
    return event


def sanitize_progress_detail(detail: object) -> str:
    clean_detail = str(detail or "")
    clean_detail = clean_detail.encode("utf-8", "replace").decode("utf-8", "replace")
    clean_detail = clean_detail.strip()
    return "".join(" " if ord(ch) < 32 else ch for ch in clean_detail)
