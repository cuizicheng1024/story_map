import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from ..core.observability import structured_log
from ..runtime.legacy_agent.runtime import aggregate_result_runtime_meta as _aggregate_result_runtime_meta
from .task_archive_refresher import TaskArchiveRefresher
from .task_execution_flow import TaskExecutionCoordinator
from .task_run_pipeline import TaskRunPipeline
from .task_state_flow import (
    build_new_task,
    build_housekeep_report,
    build_housekeep_skip_report,
    build_progress_event,
    build_runtime_metrics_snapshot,
    collect_auto_retry_task_ids,
    collect_orphan_task_ids,
    mark_task_interrupted,
    normalize_recovered_tasks,
    retry_allowed_for_task,
    retry_count_for_task,
    sanitize_progress_detail,
)
from .task_storage_backend import TaskStorageBackend
from .task_target_resolver import resolve_task_targets
from .task_debug import build_task_debug_payload
from .task_schema import (
    TaskListItem,
    TaskSnapshot,
    TaskStorageMaintenanceResult,
    TaskStorageQueryResult,
    TaskStorageStats,
    build_task_list_item,
    build_task_snapshot,
)


_TERMINAL_TASK_STATUSES = {"completed", "failed", "partial_failed", "interrupted", "cancelled", "timed_out"}
_ACTIVE_TASK_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class TaskAgentDeps:
    """LLM 与人物抽取/生成相关的核心依赖。"""
    get_llm_client: Callable[..., object]
    extract_historical_figures: Callable[[object, str], List[str]]
    generate_for_person: Callable[..., Dict[str, object]]


@dataclass(frozen=True)
class TaskExportDeps:
    """导出/输出相关依赖（HTML、CSV、重合度等）。"""
    ensure_profile_exports: Callable[..., Dict[str, str]]
    ensure_multi_exports: Callable[..., Dict[str, str]]
    compute_overlaps: Callable[[List[Dict[str, object]]], List[Dict[str, object]]]
    build_conclusion: Callable[[List[Dict[str, object]], bool], str]
    render_multi_html: Callable[[Dict[str, object]], str]
    save_html: Callable[[str, str], str]
    relative_path: Callable[[str], str]


@dataclass(frozen=True)
class TaskConfig:
    """任务调度配置（并发度、调色板、日志器等）。"""
    logger: object
    max_concurrency: int
    color_palette: Tuple[str, ...]
    project_root: Callable[[], str]
    format_seconds: Callable[[float], str]
    validate_input_text: Callable[[str], str]
    task_ttl_seconds: int = 3600
    max_tasks: int = 200


class _TaskCancelled(RuntimeError):
    pass


class _TaskTimedOut(RuntimeError):
    pass


def _collect_result_runtime_meta(results: List[Dict[str, object]]) -> Dict[str, object]:
    return _aggregate_result_runtime_meta(results)


def _normalize_task_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()


class TaskService:
    def __init__(
        self,
        *,
        config: Optional[TaskConfig] = None,
        agent: Optional[TaskAgentDeps] = None,
        exports: Optional[TaskExportDeps] = None,
        refresh_stellar_homepage: Optional[Callable[[str], Dict[str, object]]] = None,
        enqueue_background_job: Optional[Callable[..., object]] = None,
        logger: Optional[object] = None,
        max_concurrency: int = 2,
        color_palette: Tuple[str, ...] = (),
        project_root: Optional[Callable[[], str]] = None,
        format_seconds: Optional[Callable[[float], str]] = None,
        validate_input_text: Optional[Callable[[str], Optional[str]]] = None,
        get_llm_client: Optional[Callable[..., object]] = None,
        extract_historical_figures: Optional[Callable[[object, str], List[str]]] = None,
        generate_for_person: Optional[Callable[..., Dict[str, object]]] = None,
        ensure_profile_exports: Optional[Callable[..., Dict[str, str]]] = None,
        ensure_multi_exports: Optional[Callable[..., Dict[str, str]]] = None,
        compute_overlaps: Optional[Callable[[List[Dict[str, object]]], List[Dict[str, object]]]] = None,
        build_conclusion: Optional[Callable[[List[Dict[str, object]], bool], str]] = None,
        render_multi_html: Optional[Callable[[Dict[str, object]], str]] = None,
        save_html: Optional[Callable[[str, str], str]] = None,
        relative_path: Optional[Callable[[str], str]] = None,
        task_ttl_seconds: int = 3600,
        max_tasks: int = 200,
    ) -> None:
        if config is None:
            config = TaskConfig(
                logger=logger or logging.getLogger(__name__),
                max_concurrency=max_concurrency,
                color_palette=tuple(color_palette or ()),
                project_root=project_root or (lambda: os.getcwd()),
                format_seconds=format_seconds or (lambda sec: f"{sec:.2f}s"),
                validate_input_text=validate_input_text or (lambda text: None if str(text).strip() else "empty"),
                task_ttl_seconds=task_ttl_seconds,
                max_tasks=max_tasks,
            )
        if agent is None:
            if get_llm_client is None or extract_historical_figures is None or generate_for_person is None:
                raise TypeError("TaskService requires agent deps or legacy generation callbacks")
            agent = TaskAgentDeps(
                get_llm_client=get_llm_client,
                extract_historical_figures=extract_historical_figures,
                generate_for_person=generate_for_person,
            )
        if exports is None:
            missing = [
                name for name, value in {
                    "ensure_profile_exports": ensure_profile_exports,
                    "ensure_multi_exports": ensure_multi_exports,
                    "compute_overlaps": compute_overlaps,
                    "build_conclusion": build_conclusion,
                    "render_multi_html": render_multi_html,
                    "save_html": save_html,
                    "relative_path": relative_path,
                }.items() if value is None
            ]
            if missing:
                raise TypeError(f"TaskService requires export deps or legacy callbacks: {', '.join(missing)}")
            exports = TaskExportDeps(
                ensure_profile_exports=ensure_profile_exports,
                ensure_multi_exports=ensure_multi_exports,
                compute_overlaps=compute_overlaps,
                build_conclusion=build_conclusion,
                render_multi_html=render_multi_html,
                save_html=save_html,
                relative_path=relative_path,
            )
        self._logger = config.logger
        self._max_concurrency = config.max_concurrency
        self._color_palette = config.color_palette
        self._project_root = config.project_root
        self._format_seconds = config.format_seconds
        self._validate_input_text = config.validate_input_text
        self._task_ttl_seconds = max(int(config.task_ttl_seconds), 60)
        self._max_tasks = max(int(config.max_tasks), 20)
        self._get_llm_client = agent.get_llm_client
        self._extract_historical_figures = agent.extract_historical_figures
        self._generate_for_person = agent.generate_for_person
        self._ensure_profile_exports = exports.ensure_profile_exports
        self._ensure_multi_exports = exports.ensure_multi_exports
        self._compute_overlaps = exports.compute_overlaps
        self._build_conclusion = exports.build_conclusion
        self._render_multi_html = exports.render_multi_html
        self._save_html = exports.save_html
        self._relative_path = exports.relative_path
        self._refresh_stellar_homepage = refresh_stellar_homepage
        self._enqueue_background_job = enqueue_background_job

        self._executor = ThreadPoolExecutor(max_workers=config.max_concurrency)
        self._archive_executor = ThreadPoolExecutor(max_workers=1)
        self._shutting_down = False
        self._queue_lock = threading.Lock()
        self._pending = 0
        self._active = 0
        self._task_lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, object]] = {}
        self._task_futures: Dict[str, Future[None]] = {}
        self._metrics_lock = threading.Lock()
        self._metrics: Dict[str, float] = {
            "submitted": 0,
            "deduped": 0,
            "retried": 0,
            "interrupted": 0,
            "auto_retried": 0,
            "cancel_requested": 0,
            "cancelled": 0,
            "timed_out": 0,
            "completed": 0,
            "failed": 0,
            "partial_failed": 0,
            "crashed": 0,
            "queue_wait_seconds_total": 0.0,
            "duration_seconds_total": 0.0,
        }
        self._housekeep_lock = threading.Lock()
        self._housekeep_min_interval_seconds = max(
            int(os.getenv("MAP_STORY_HOUSEKEEP_MIN_INTERVAL_SECONDS", "30") or "30"),
            1,
        )
        self._last_housekeep_report: Dict[str, object] = {
            "ok": True,
            "ran": False,
            "pruned_count": 0,
            "repaired_interrupted_count": 0,
            "auto_retried_count": 0,
            "orphan_task_ids": [],
            "ran_at": 0.0,
        }
        self._task_timeout_seconds = max(int(os.getenv("MAP_STORY_TASK_TIMEOUT_SECONDS", "240") or "240"), 1)
        self._readiness_max_pending = max(
            int(os.getenv("MAP_STORY_READINESS_MAX_PENDING", str(max(self._max_concurrency * 4, 8))) or max(self._max_concurrency * 4, 8)),
            1,
        )
        self._readiness_max_running_age_seconds = max(
            int(
                os.getenv(
                    "MAP_STORY_READINESS_MAX_RUNNING_AGE_SECONDS",
                    str(self._task_timeout_seconds + 60),
                )
                or str(self._task_timeout_seconds + 60)
            ),
            self._task_timeout_seconds,
        )
        self._restart_retry_limit = max(int(os.getenv("MAP_STORY_INTERRUPTED_RETRY_LIMIT", "1") or "1"), 0)
        self._auto_retry_interrupted = str(os.getenv("MAP_STORY_AUTO_RETRY_INTERRUPTED", "1") or "1").strip().lower() not in {
            "",
            "0",
            "false",
            "off",
            "no",
        }
        runtime_dir = os.path.join(self._project_root(), "artifacts", "runtime")
        self._state_db_path = os.path.join(runtime_dir, "task_state.sqlite3")
        self._legacy_state_path = os.path.join(runtime_dir, "task_state.json")
        self._storage = TaskStorageBackend(db_path=self._state_db_path, logger=self._logger)
        self._archive_refresher = TaskArchiveRefresher(
            logger=self._logger,
            refresh_stellar_homepage=self._refresh_stellar_homepage,
            enqueue_background_job=self._enqueue_background_job,
            archive_executor=self._archive_executor,
            can_continue=self._can_continue_archive_task,
            update_archive=self._update_task_result_archive,
            append_progress=self._append_progress,
        )
        self._execution_coordinator = TaskExecutionCoordinator(
            executor=self._executor,
            max_concurrency=self._max_concurrency,
            format_seconds=self._format_seconds,
            task_timeout_seconds=self._task_timeout_seconds,
            logger=self._logger,
            reserve_queue_slot=self._reserve_queue_slot,
            activate_queue_slot=self._activate_queue_slot,
            release_active_slot=self._release_active_slot,
            refresh_queued_queue_state=self._refresh_queued_queue_state,
            register_future=self._register_task_future,
            unregister_future=self._unregister_task_future,
            update_task=self._update_task,
            append_progress=self._append_progress,
            record_metrics=self._record_metrics,
            ensure_task_can_continue=self._ensure_task_can_continue,
            run_task=self._run_task,
        )
        self._run_pipeline = TaskRunPipeline(
            color_palette=self._color_palette,
            format_seconds=self._format_seconds,
            generate_for_person=self._generate_for_person,
            ensure_profile_exports=self._ensure_profile_exports,
            ensure_multi_exports=self._ensure_multi_exports,
            compute_overlaps=self._compute_overlaps,
            build_conclusion=self._build_conclusion,
            render_multi_html=self._render_multi_html,
            save_html=self._save_html,
            relative_path=self._relative_path,
            collect_result_runtime_meta=_collect_result_runtime_meta,
        )
        self._load_tasks_from_disk()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._executor.shutdown(wait=False)
        self._archive_executor.shutdown(wait=False)

    def _load_tasks_from_sqlite(self) -> Dict[str, Dict[str, object]]:
        return self._storage.load_tasks()

    def _load_tasks_from_legacy_json(self) -> Dict[str, Dict[str, object]]:
        try:
            with open(self._legacy_state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:
            self._logger.warning("task_state_load_failed path=%s error=%s", self._legacy_state_path, exc)
            return {}
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list):
            return {}
        recovered: Dict[str, Dict[str, object]] = {}
        for item in tasks:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("id") or "").strip()
            if task_id:
                recovered[task_id] = dict(item)
        return recovered

    def _load_tasks_from_disk(self) -> None:
        recovered = self._load_tasks_from_sqlite()
        if not recovered:
            recovered = self._load_tasks_from_legacy_json()
        now = time.time()
        normalized, interrupted_ids = normalize_recovered_tasks(
            recovered,
            now=now,
            auto_retry_interrupted=self._auto_retry_interrupted,
            active_statuses=_ACTIVE_TASK_STATUSES,
        )
        with self._task_lock:
            self._tasks = normalized
            self._trim_tasks_locked()
            self._replace_all_tasks_locked()
        for task_id in interrupted_ids:
            self._record_metrics(interrupted=1)
            if self._auto_retry_interrupted:
                self._auto_retry_interrupted_task(task_id)

    def _query_tasks_from_db(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str = "",
    ) -> tuple[List[Dict[str, object]], int]:
        return self._storage.query_tasks(limit=limit, offset=offset, status=status)

    def list_tasks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str = "",
    ) -> TaskStorageQueryResult:
        self._cleanup_tasks()
        tasks, total = self._query_tasks_from_db(limit=limit, offset=offset, status=status)
        items: List[TaskListItem] = [build_task_list_item(task) for task in tasks]
        return {
            "ok": True,
            "limit": max(1, min(int(limit), 200)),
            "offset": max(0, int(offset)),
            "status": str(status or "").strip(),
            "total": total,
            "tasks": items,
        }

    def storage_stats(self) -> TaskStorageStats:
        self._cleanup_tasks()
        counts = {
            "queued_count": 0,
            "running_count": 0,
            "completed_count": 0,
            "partial_failed_count": 0,
            "failed_count": 0,
        }
        oldest = 0.0
        newest = 0.0
        with self._task_lock:
            for task in self._tasks.values():
                status = str(task.get("status") or "").strip()
                key = f"{status}_count"
                if key in counts:
                    counts[key] += 1
                updated_at = float(task.get("updated_at") or 0)
                if updated_at > 0:
                    if oldest <= 0 or updated_at < oldest:
                        oldest = updated_at
                    if updated_at > newest:
                        newest = updated_at
        file_sizes = self._storage.file_sizes()
        return {
            "db_path": self._state_db_path,
            "db_size_bytes": int(file_sizes["total_size_bytes"]),
            "db_main_size_bytes": int(file_sizes["main_size_bytes"]),
            "db_wal_size_bytes": int(file_sizes["wal_size_bytes"]),
            "db_shm_size_bytes": int(file_sizes["shm_size_bytes"]),
            "task_count": sum(counts.values()),
            "queued_count": counts["queued_count"],
            "running_count": counts["running_count"],
            "completed_count": counts["completed_count"],
            "partial_failed_count": counts["partial_failed_count"],
            "failed_count": counts["failed_count"],
            "oldest_updated_at": oldest,
            "newest_updated_at": newest,
        }

    def maintain_storage(
        self,
        *,
        prune_expired: bool = True,
        vacuum: bool = False,
        reconcile: bool = False,
        auto_retry: bool = True,
    ) -> TaskStorageMaintenanceResult:
        before_ids = set()
        with self._task_lock:
            before_ids = set(self._tasks.keys())
        if prune_expired:
            self._cleanup_tasks()
        reconciled: Dict[str, object] = {
            "ok": True,
            "ran": False,
            "pruned_count": 0,
            "repaired_interrupted_count": 0,
            "auto_retried_count": 0,
            "orphan_task_ids": [],
            "ran_at": 0.0,
        }
        if reconcile:
            reconciled = self.housekeep_runtime(force=True, auto_retry=auto_retry)
        after_ids = set()
        with self._task_lock:
            after_ids = set(self._tasks.keys())
        pruned_count = max(0, len(before_ids - after_ids))
        if vacuum:
            with self._task_lock:
                self._storage.vacuum()
        return {
            "ok": True,
            "pruned_count": pruned_count,
            "vacuumed": bool(vacuum),
            "reconciled": reconciled,
            "stats": self.storage_stats(),
        }

    def task_debug_snapshot(self, task_id: str) -> Dict[str, object]:
        snapshot = self.snapshot_task(task_id)
        if not snapshot.get("exists"):
            return snapshot
        snapshot["debug"] = build_task_debug_payload(snapshot)
        return snapshot

    def _record_metrics(self, **increments: float) -> None:
        with self._metrics_lock:
            for key, amount in increments.items():
                if key not in self._metrics:
                    self._metrics[key] = 0.0
                self._metrics[key] = float(self._metrics.get(key, 0.0)) + float(amount)

    def runtime_metrics_snapshot(self) -> Dict[str, object]:
        self._cleanup_tasks()
        with self._queue_lock:
            queue = {"pending": int(self._pending), "active": int(self._active), "limit": int(self._max_concurrency)}
        now = time.time()
        with self._task_lock:
            tasks = dict(self._tasks)
        with self._metrics_lock:
            metrics = dict(self._metrics)
        return build_runtime_metrics_snapshot(
            tasks=tasks,
            queue=queue,
            metrics=metrics,
            now=now,
            readiness_max_pending=self._readiness_max_pending,
            readiness_max_running_age_seconds=self._readiness_max_running_age_seconds,
            task_timeout_seconds=self._task_timeout_seconds,
            housekeep_min_interval_seconds=self._housekeep_min_interval_seconds,
            last_housekeep_report=self._last_housekeep_report,
        )

    def _retry_count_for_task(self, task: Dict[str, object]) -> int:
        return retry_count_for_task(task)

    def _retry_allowed_for_task(self, task: Dict[str, object]) -> bool:
        return retry_allowed_for_task(
            task,
            terminal_statuses=_TERMINAL_TASK_STATUSES,
            retry_limit=self._restart_retry_limit,
        )

    def _auto_retry_interrupted_task(self, task_id: str) -> None:
        payload = self.retry_task(task_id, reason="服务重启自动补偿", auto=True)
        if payload.get("ok"):
            self._record_metrics(auto_retried=1)
            structured_log(
                self._logger,
                "info",
                "task_interrupted_auto_retry",
                task_id=task_id,
                retry_task_id=payload.get("task_id"),
            )

    def _mark_task_interrupted_by_housekeep(self, task_id: str, detail: str) -> bool:
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return False
        current_time = time.time()
        with self._task_lock:
            task = self._tasks.get(normalized_id)
            if not task:
                return False
            if not mark_task_interrupted(
                task,
                now=current_time,
                detail=str(detail or "").strip() or "后台巡检发现任务状态异常，已转为中断，可重试恢复。",
                auto_retry_interrupted=self._auto_retry_interrupted,
                active_statuses=_ACTIVE_TASK_STATUSES,
                progress_label="巡检修复",
            ):
                return False
            self._upsert_task_locked(task)
        self._record_metrics(interrupted=1)
        structured_log(self._logger, "warning", "task_housekeep_interrupted", task_id=normalized_id, detail=detail)
        return True

    def housekeep_runtime(self, *, force: bool = False, auto_retry: bool = True) -> Dict[str, object]:
        now = time.time()
        with self._housekeep_lock:
            previous = dict(self._last_housekeep_report)
            last_ran_at = float(previous.get("ran_at") or 0.0)
            if not force and last_ran_at > 0 and (now - last_ran_at) < self._housekeep_min_interval_seconds:
                return build_housekeep_skip_report(previous, last_ran_at=last_ran_at)
            report: Dict[str, object] = build_housekeep_report(now=now)
            with self._task_lock:
                before_ids = set(self._tasks.keys())
            self._cleanup_tasks()
            with self._task_lock:
                after_ids = set(self._tasks.keys())
                current_tasks = dict(self._tasks)
                current_futures = dict(self._task_futures)
            report["pruned_count"] = max(0, len(before_ids - after_ids))
            orphan_task_ids = collect_orphan_task_ids(
                tasks=current_tasks,
                task_futures=current_futures,
                now=now,
                active_statuses=_ACTIVE_TASK_STATUSES,
                task_timeout_seconds=self._task_timeout_seconds,
                housekeep_min_interval_seconds=self._housekeep_min_interval_seconds,
            )
            repaired_count = 0
            for task_id in orphan_task_ids:
                if self._mark_task_interrupted_by_housekeep(task_id, "后台巡检发现任务控制流丢失，已标记为中断，可重试恢复。"):
                    repaired_count += 1
            with self._task_lock:
                retry_scan_tasks = dict(self._tasks)
            auto_retry_ids = collect_auto_retry_task_ids(
                tasks=retry_scan_tasks,
                auto_retry=auto_retry,
                retry_allowed=self._retry_allowed_for_task,
            )
            auto_retried_count = 0
            for task_id in auto_retry_ids:
                payload = self.retry_task(task_id, reason="后台巡检自动补偿", auto=True)
                if payload.get("ok"):
                    auto_retried_count += 1
            report["repaired_interrupted_count"] = repaired_count
            report["auto_retried_count"] = auto_retried_count
            report["orphan_task_ids"] = orphan_task_ids
            self._last_housekeep_report = dict(report)
            if report["pruned_count"] or repaired_count or auto_retried_count:
                structured_log(
                    self._logger,
                    "info",
                    "task_housekeep_completed",
                    pruned_count=report["pruned_count"],
                    repaired_interrupted_count=repaired_count,
                    auto_retried_count=auto_retried_count,
                    orphan_task_ids=orphan_task_ids,
                )
            return dict(report)

    def _active_duplicate_task(self, dedupe_key: str) -> Optional[Dict[str, object]]:
        if not dedupe_key:
            return None
        with self._task_lock:
            for task in self._tasks.values():
                if str(task.get("dedupe_key") or "").strip() != dedupe_key:
                    continue
                status = str(task.get("status") or "").strip()
                if status in _ACTIVE_TASK_STATUSES:
                    return dict(task)
        return None

    def _task_control_snapshot(self, task_id: str) -> Tuple[bool, str, float]:
        with self._task_lock:
            task = self._tasks.get(task_id) or {}
            cancel_requested = bool(task.get("cancel_requested"))
            cancel_reason = str(task.get("cancel_reason") or "").strip()
            deadline_at = float(task.get("deadline_at") or 0.0)
        return cancel_requested, cancel_reason, deadline_at

    def _ensure_task_can_continue(self, task_id: str) -> None:
        cancel_requested, cancel_reason, deadline_at = self._task_control_snapshot(task_id)
        if cancel_requested:
            raise _TaskCancelled(cancel_reason or "任务已取消。")
        if deadline_at > 0 and time.monotonic() >= deadline_at:
            raise _TaskTimedOut(f"任务执行超时，已超过 {self._task_timeout_seconds} 秒。")

    def _task_timeout_resolver(self, task_id: str) -> int:
        _, _, deadline_at = self._task_control_snapshot(task_id)
        if deadline_at <= 0:
            return int(self._task_timeout_seconds)
        remaining = int(deadline_at - time.monotonic())
        return max(1, remaining)

    def _refresh_queued_queue_state(self) -> None:
        with self._queue_lock:
            active_now = self._active
        with self._task_lock:
            queued = sorted(
                (
                    (task_id, task)
                    for task_id, task in self._tasks.items()
                    if str(task.get("status") or "").strip() == "queued"
                ),
                key=lambda item: (float(item[1].get("created_at") or 0), str(item[0])),
            )
            position = 0
            for _task_id, task in queued:
                pending_queue = dict(task.get("queue") or {})
                if pending_queue.get("active") == 0 and position == 0:
                    continue
                position += 1
                queue = dict(task.get("queue") or {})
                queue["position"] = position
                queue["limit"] = self._max_concurrency
                queue["active"] = active_now
                task["queue"] = queue
                task["updated_at"] = time.time()
                self._upsert_task_locked(task)

    def _reserve_queue_slot(self) -> Tuple[int, int]:
        with self._queue_lock:
            self._pending += 1
            return self._pending, self._active

    def _activate_queue_slot(self) -> int:
        with self._queue_lock:
            if self._pending > 0:
                self._pending -= 1
            self._active += 1
            return self._active

    def _release_active_slot(self) -> None:
        with self._queue_lock:
            if self._active > 0:
                self._active -= 1

    def _register_task_future(self, task_id: str, future: Future[None]) -> None:
        with self._task_lock:
            self._task_futures[task_id] = future

    def _unregister_task_future(self, task_id: str) -> None:
        with self._task_lock:
            self._task_futures.pop(task_id, None)

    def _upsert_task_locked(self, task: Dict[str, object]) -> None:
        self._storage.upsert_task(task)

    def _delete_tasks_locked(self, task_ids: List[str]) -> None:
        self._storage.delete_tasks(task_ids)

    def _replace_all_tasks_locked(self) -> None:
        self._storage.replace_all_tasks(self._tasks.values())

    def snapshot_task(self, task_id: str) -> TaskSnapshot:
        self._cleanup_tasks()
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"exists": False, "ok": False, "error": "task not found"}
            return build_task_snapshot(task)

    def submit_task(
        self,
        text: str,
        *,
        dedupe: bool = True,
        retry_of: str = "",
        retry_count: int = 0,
        retry_reason: str = "",
        trigger: str = "user",
    ) -> Dict[str, object]:
        self._cleanup_tasks()
        error = self._validate_input_text(text)
        if error:
            return {"ok": False, "error": error}
        dedupe_key = _normalize_task_text(text)
        if dedupe:
            existing = self._active_duplicate_task(dedupe_key)
            if existing:
                self._record_metrics(deduped=1)
                return {
                    "ok": True,
                    "task_id": str(existing.get("id") or ""),
                    "queue": dict(existing.get("queue") or {}),
                    "deduped": True,
                }
        task_id = self._create_task(
            text,
            dedupe_key=dedupe_key,
            retry_of=retry_of,
            retry_count=retry_count,
            retry_reason=retry_reason,
            trigger=trigger,
        )
        self._record_metrics(submitted=1)
        if retry_of:
            self._record_metrics(retried=1)
        return self._execution_coordinator.submit(
            task_id=task_id,
            text=text,
            cancelled_exc_type=_TaskCancelled,
            timed_out_exc_type=_TaskTimedOut,
        )

    def retry_task(self, task_id: str, *, reason: str = "", auto: bool = False) -> Dict[str, object]:
        self._cleanup_tasks()
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return {"ok": False, "error": "id required"}
        with self._task_lock:
            task = self._tasks.get(normalized_id)
            if not task:
                return {"ok": False, "error": "task not found"}
            if not self._retry_allowed_for_task(task):
                return {"ok": False, "error": "task not retryable", "status": str(task.get('status') or '')}
            text = str(task.get("text") or "").strip()
            current_retry_count = self._retry_count_for_task(task)
        if not text:
            return {"ok": False, "error": "task text missing"}
        retry_reason = str(reason or "").strip() or ("服务重启自动补偿" if auto else "用户重试任务")
        payload = self.submit_task(
            text,
            dedupe=False,
            retry_of=normalized_id,
            retry_count=current_retry_count + 1,
            retry_reason=retry_reason,
            trigger="auto_retry" if auto else "retry",
        )
        if not payload.get("ok"):
            return payload
        retry_task_id = str(payload.get("task_id") or "").strip()
        self._update_task(
            normalized_id,
            auto_retry_pending=False,
            retry_task_id=retry_task_id,
            retry_count=current_retry_count + 1,
            retry_reason=retry_reason,
            retried_at=time.time(),
        )
        self._append_progress(normalized_id, "重试", f"{retry_reason} -> {retry_task_id}")
        return {
            "ok": True,
            "task_id": retry_task_id,
            "retried_from": normalized_id,
            "auto": bool(auto),
            "status": "queued",
        }

    def cancel_task(self, task_id: str, *, reason: str = "") -> Dict[str, object]:
        self._cleanup_tasks()
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return {"ok": False, "error": "id required"}
        message = str(reason or "").strip() or "用户取消了任务。"
        with self._task_lock:
            task = self._tasks.get(normalized_id)
            if not task:
                return {"ok": False, "error": "task not found"}
            status = str(task.get("status") or "").strip()
            if status in _TERMINAL_TASK_STATUSES:
                return {"ok": False, "error": f"task already {status}", "status": status}
            task["cancel_requested"] = True
            task["cancel_reason"] = message
            task["updated_at"] = time.time()
            self._upsert_task_locked(task)
            future = self._task_futures.get(normalized_id)
        self._record_metrics(cancel_requested=1)
        if future is not None and future.cancel():
            with self._queue_lock:
                if self._pending > 0:
                    self._pending -= 1
            self._update_task(normalized_id, status="cancelled", error=message)
            self._append_progress(normalized_id, "取消", message)
            self._append_progress(normalized_id, "完成", "已取消")
            self._record_metrics(cancelled=1)
            with self._task_lock:
                self._task_futures.pop(normalized_id, None)
            self._refresh_queued_queue_state()
            return {"ok": True, "task_id": normalized_id, "status": "cancelled"}
        self._append_progress(normalized_id, "取消", "已收到取消请求，等待当前步骤收口。")
        return {"ok": True, "task_id": normalized_id, "status": "cancelling"}

    def _create_task(
        self,
        text: str,
        *,
        dedupe_key: str = "",
        retry_of: str = "",
        retry_count: int = 0,
        retry_reason: str = "",
        trigger: str = "user",
    ) -> str:
        task_id = uuid.uuid4().hex
        now = time.time()
        task = build_new_task(
            task_id=task_id,
            text=text,
            dedupe_key=dedupe_key,
            now=now,
            deadline_at=time.monotonic() + self._task_timeout_seconds,
            timeout_seconds=self._task_timeout_seconds,
            retry_of=retry_of,
            retry_count=retry_count,
            retry_reason=retry_reason,
            trigger=trigger,
        )
        with self._task_lock:
            self._tasks[task_id] = task
            removed_ids = self._trim_tasks_locked()
            self._upsert_task_locked(task)
            self._delete_tasks_locked(removed_ids)
        return task_id

    def _cleanup_tasks(self) -> None:
        cutoff = time.time() - self._task_ttl_seconds
        with self._task_lock:
            expired_ids = [
                task_id
                for task_id, task in self._tasks.items()
                if task.get("status") in _TERMINAL_TASK_STATUSES
                and float(task.get("updated_at") or 0) < cutoff
            ]
            for task_id in expired_ids:
                self._tasks.pop(task_id, None)
                self._task_futures.pop(task_id, None)
            removed_ids = expired_ids + self._trim_tasks_locked()
            self._delete_tasks_locked(removed_ids)

    def _trim_tasks_locked(self) -> List[str]:
        removed_ids: List[str] = []
        overflow = len(self._tasks) - self._max_tasks
        if overflow <= 0:
            return removed_ids
        # 优先丢弃已结束且最久未更新的任务，避免运行中的任务被提前清理。
        ordered = sorted(
            self._tasks.items(),
            key=lambda item: (
                    item[1].get("status") not in _TERMINAL_TASK_STATUSES,
                float(item[1].get("updated_at") or 0),
            ),
        )
        for task_id, task in ordered:
            if overflow <= 0:
                break
            if task.get("status") not in _TERMINAL_TASK_STATUSES:
                continue
            self._tasks.pop(task_id, None)
            self._task_futures.pop(task_id, None)
            removed_ids.append(task_id)
            overflow -= 1
        return removed_ids

    def _update_task(self, task_id: str, **fields: object) -> None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(fields)
            task["updated_at"] = time.time()
            removed_ids = self._trim_tasks_locked()
            self._upsert_task_locked(task)
            self._delete_tasks_locked(removed_ids)

    def _update_task_result_archive(self, task_id: str, archive: Dict[str, object]) -> None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            result = dict(task.get("result") or {}) if isinstance(task.get("result"), dict) else {}
            result["archive"] = dict(archive or {})
            task["result"] = result
            task["updated_at"] = time.time()
            removed_ids = self._trim_tasks_locked()
            self._upsert_task_locked(task)
            self._delete_tasks_locked(removed_ids)

    def _append_progress(self, task_id: str, label: str, detail: str = "") -> None:
        event = build_progress_event(label, detail=sanitize_progress_detail(detail))
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["progress"].append(event)
            task["updated_at"] = time.time()
            self._upsert_task_locked(task)

    def _can_continue_archive_task(self, task_id: str) -> bool:
        try:
            self._ensure_task_can_continue(task_id)
            return True
        except (_TaskCancelled, _TaskTimedOut):
            return False

    def _enqueue_archive_refresh(self, task_id: str, people: List[str]) -> None:
        self._archive_refresher.enqueue(task_id, people, shutting_down=self._shutting_down)

    def _sync_run_pipeline_dependencies(self) -> None:
        # Keep the pipeline aligned with TaskService attributes so tests and
        # runtime hot-swaps can patch the service entrypoints directly.
        self._run_pipeline._generate_for_person = self._generate_for_person
        self._run_pipeline._ensure_profile_exports = self._ensure_profile_exports
        self._run_pipeline._ensure_multi_exports = self._ensure_multi_exports
        self._run_pipeline._compute_overlaps = self._compute_overlaps
        self._run_pipeline._build_conclusion = self._build_conclusion
        self._run_pipeline._render_multi_html = self._render_multi_html
        self._run_pipeline._save_html = self._save_html
        self._run_pipeline._relative_path = self._relative_path

    def _run_task(self, task_id: str, text: str, allow_cache: bool = True) -> None:
        started_at = time.perf_counter()
        self._logger.info("task_start id=%s text=%s", task_id, text)
        structured_log(self._logger, "info", "task_start", task_id=task_id, text=text)
        self._update_task(task_id, status="running")
        self._append_progress(task_id, "理解任务")
        self._ensure_task_can_continue(task_id)

        def _llm_event(message: str) -> None:
            self._ensure_task_can_continue(task_id)
            self._append_progress(task_id, "模型调用", message)

        target_resolution = resolve_task_targets(
            text=text,
            project_root=self._project_root,
            get_llm_client=self._get_llm_client,
            extract_historical_figures=self._extract_historical_figures,
            timeout_seconds=lambda: self._task_timeout_resolver(task_id),
            ensure_can_continue=lambda: self._ensure_task_can_continue(task_id),
            append_progress=lambda label, detail="": self._append_progress(task_id, label, detail),
            llm_event=_llm_event,
        )
        client = target_resolution.client
        resolved_targets = list(target_resolution.resolved_targets)
        targets = list(target_resolution.generation_targets)
        blocked_results = list(target_resolution.blocked_results)
        if target_resolution.error_message:
            self._update_task(task_id, status="failed", error=target_resolution.error_message)
            self._append_progress(task_id, "失败", target_resolution.error_message)
            self._append_progress(task_id, "完成", "失败")
            self._record_metrics(failed=1, duration_seconds_total=max(0.0, time.perf_counter() - started_at))
            self._logger.warning("task_failed id=%s error=%s", task_id, target_resolution.error_message)
            return
        self._sync_run_pipeline_dependencies()
        artifacts = self._run_pipeline.build_generation_artifacts(
            task_id=task_id,
            client=client,
            targets=targets,
            blocked_results=blocked_results,
            allow_cache=allow_cache,
            ensure_can_continue=lambda: self._ensure_task_can_continue(task_id),
            append_progress=lambda label, detail="": self._append_progress(task_id, label, detail),
            llm_event=_llm_event,
            timeout_seconds=lambda: self._task_timeout_resolver(task_id),
        )
        duration, outcome, terminal_resolution = self._run_pipeline.build_outcome(
            resolved_targets=resolved_targets,
            artifacts=artifacts,
            started_at=started_at,
        )
        summary = outcome.summary
        successful_people = outcome.successful_people
        duration_seconds = max(0.0, time.perf_counter() - started_at)
        self._run_pipeline.apply_terminal_resolution(
            task_id=task_id,
            summary=summary,
            successful_people=successful_people,
            terminal_resolution=terminal_resolution,
            duration=duration,
            duration_seconds=duration_seconds,
            refresh_stellar_homepage=self._refresh_stellar_homepage,
            update_task=self._update_task,
            enqueue_archive_refresh=self._enqueue_archive_refresh,
            append_progress=lambda label, detail="": self._append_progress(task_id, label, detail),
            record_metrics=self._record_metrics,
            logger=self._logger,
        )
