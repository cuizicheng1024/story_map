import json
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    from .project_paths import classify_story_person_authenticity, known_authentic_person_names, story_person_names
    from .story_agent_runtime import aggregate_result_runtime_meta as _aggregate_result_runtime_meta
    from .story_task_debug import build_task_debug_payload
    from .story_task_schema import (
        TaskFileEntry,
        TaskListItem,
        TaskMultiEntry,
        TaskResultSummary,
        TaskSnapshot,
        TaskStorageMaintenanceResult,
        TaskStorageQueryResult,
        TaskStorageStats,
        build_task_list_item,
        build_task_result_summary,
        build_task_snapshot,
    )
except ImportError:
    from project_paths import classify_story_person_authenticity, known_authentic_person_names, story_person_names
    from story_agent_runtime import aggregate_result_runtime_meta as _aggregate_result_runtime_meta
    from story_task_debug import build_task_debug_payload
    from story_task_schema import (
        TaskFileEntry,
        TaskListItem,
        TaskMultiEntry,
        TaskResultSummary,
        TaskSnapshot,
        TaskStorageMaintenanceResult,
        TaskStorageQueryResult,
        TaskStorageStats,
        build_task_list_item,
        build_task_result_summary,
        build_task_snapshot,
    )


_TASK_LIKE_TOKENS = (
    "为什么",
    "为何",
    "如何",
    "怎么",
    "请",
    "帮我",
    "比较",
    "对比",
    "分析",
    "总结",
    "解释",
    "给我",
    "什么",
    "哪里",
    "哪儿",
    "谁",
    "轨迹",
    "足迹",
    "证据",
    "活动",
)
_TERMINAL_TASK_STATUSES = {"completed", "failed", "partial_failed"}


def _collect_result_runtime_meta(results: List[Dict[str, object]]) -> Dict[str, object]:
    return _aggregate_result_runtime_meta(results)


def _looks_like_person_atom(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) > 12:
        return False
    if re.search(r"[?？!！。:：；;（）()\[\]{}<>]", cleaned):
        return False
    return not any(token in cleaned for token in _TASK_LIKE_TOKENS)


def _is_usable_result(result: Dict[str, object]) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


def _has_task_blocking_failure(result: Dict[str, object]) -> bool:
    return bool(result.get("homepage_refresh_failed"))


class TaskService:
    def __init__(
        self,
        *,
        logger: object,
        max_concurrency: int,
        color_palette: Tuple[str, ...],
        project_root: Callable[[], str],
        format_seconds: Callable[[float], str],
        validate_input_text: Callable[[str], str],
        get_llm_client: Callable[..., object],
        extract_historical_figures: Callable[[object, str], List[str]],
        generate_for_person: Callable[..., Dict[str, object]],
        ensure_profile_exports: Callable[..., Dict[str, str]],
        ensure_multi_exports: Callable[..., Dict[str, str]],
        compute_overlaps: Callable[[List[Dict[str, object]]], List[Dict[str, object]]],
        build_conclusion: Callable[[List[Dict[str, object]], bool], str],
        render_multi_html: Callable[[Dict[str, object]], str],
        save_html: Callable[[str, str], str],
        relative_path: Callable[[str], str],
        task_ttl_seconds: int = 3600,
        max_tasks: int = 200,
    ) -> None:
        self._logger = logger
        self._max_concurrency = max_concurrency
        self._color_palette = color_palette
        self._project_root = project_root
        self._format_seconds = format_seconds
        self._validate_input_text = validate_input_text
        self._get_llm_client = get_llm_client
        self._extract_historical_figures = extract_historical_figures
        self._generate_for_person = generate_for_person
        self._ensure_profile_exports = ensure_profile_exports
        self._ensure_multi_exports = ensure_multi_exports
        self._compute_overlaps = compute_overlaps
        self._build_conclusion = build_conclusion
        self._render_multi_html = render_multi_html
        self._save_html = save_html
        self._relative_path = relative_path
        self._task_ttl_seconds = max(int(task_ttl_seconds), 60)
        self._max_tasks = max(int(max_tasks), 20)

        self._executor = ThreadPoolExecutor(max_workers=max_concurrency)
        self._queue_lock = threading.Lock()
        self._pending = 0
        self._active = 0
        self._task_lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, object]] = {}
        runtime_dir = os.path.join(self._project_root(), "artifacts", "runtime")
        self._state_db_path = os.path.join(runtime_dir, "task_state.sqlite3")
        self._legacy_state_path = os.path.join(runtime_dir, "task_state.json")
        self._db = self._open_task_db()
        self._ensure_task_table()
        self._load_tasks_from_disk()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def _open_task_db(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._state_db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._state_db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_task_table(self) -> None:
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_updated_at
                ON tasks(updated_at)
                """
            )

    def _load_tasks_from_sqlite(self) -> Dict[str, Dict[str, object]]:
        recovered: Dict[str, Dict[str, object]] = {}
        try:
            rows = self._db.execute("SELECT id, payload FROM tasks").fetchall()
        except Exception as exc:
            self._logger.warning("task_state_load_failed path=%s error=%s", self._state_db_path, exc)
            return recovered
        for task_id, payload_text in rows:
            try:
                payload = json.loads(str(payload_text or ""))
            except Exception:
                continue
            if isinstance(payload, dict):
                recovered[str(task_id)] = payload
        return recovered

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
        normalized: Dict[str, Dict[str, object]] = {}
        for task_id, item in recovered.items():
            task = dict(item or {})
            if task.get("status") in {"queued", "running"}:
                progress = list(task.get("progress") or [])
                progress.append(
                    {
                        "label": "中断",
                        "time": time.strftime("%H:%M:%S", time.localtime(now)),
                        "detail": "服务重启导致任务中断，请重新提交。",
                    }
                )
                task["progress"] = progress
                task["status"] = "failed"
                task["error"] = "服务重启导致任务中断，请重新提交。"
                task["updated_at"] = now
            normalized[str(task_id)] = task
        with self._task_lock:
            self._tasks = normalized
            self._trim_tasks_locked()
            self._replace_all_tasks_locked()

    def _query_tasks_from_db(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str = "",
    ) -> tuple[List[Dict[str, object]], int]:
        normalized_status = str(status or "").strip()
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        rows = self._db.execute("SELECT payload FROM tasks ORDER BY updated_at DESC").fetchall()
        filtered: List[Dict[str, object]] = []
        for (payload_text,) in rows:
            try:
                payload = json.loads(str(payload_text or ""))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if normalized_status and str(payload.get("status") or "").strip() != normalized_status:
                continue
            filtered.append(payload)
        total = len(filtered)
        return filtered[safe_offset : safe_offset + safe_limit], total

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
        main_size = 0
        wal_size = 0
        shm_size = 0
        try:
            main_size = os.path.getsize(self._state_db_path) if os.path.exists(self._state_db_path) else 0
        except Exception:
            main_size = 0
        try:
            wal_size = os.path.getsize(f"{self._state_db_path}-wal") if os.path.exists(f"{self._state_db_path}-wal") else 0
        except Exception:
            wal_size = 0
        try:
            shm_size = os.path.getsize(f"{self._state_db_path}-shm") if os.path.exists(f"{self._state_db_path}-shm") else 0
        except Exception:
            shm_size = 0
        size_bytes = int(main_size) + int(wal_size) + int(shm_size)
        return {
            "db_path": self._state_db_path,
            "db_size_bytes": int(size_bytes),
            "db_main_size_bytes": int(main_size),
            "db_wal_size_bytes": int(wal_size),
            "db_shm_size_bytes": int(shm_size),
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
    ) -> TaskStorageMaintenanceResult:
        before_ids = set()
        with self._task_lock:
            before_ids = set(self._tasks.keys())
        if prune_expired:
            self._cleanup_tasks()
        after_ids = set()
        with self._task_lock:
            after_ids = set(self._tasks.keys())
        pruned_count = max(0, len(before_ids - after_ids))
        if vacuum:
            with self._task_lock:
                self._db.commit()
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._db.execute("VACUUM")
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {
            "ok": True,
            "pruned_count": pruned_count,
            "vacuumed": bool(vacuum),
            "stats": self.storage_stats(),
        }

    def task_debug_snapshot(self, task_id: str) -> Dict[str, object]:
        snapshot = self.snapshot_task(task_id)
        if not snapshot.get("exists"):
            return snapshot
        snapshot["debug"] = build_task_debug_payload(snapshot)
        return snapshot

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
            for position, (_task_id, task) in enumerate(queued, start=1):
                queue = dict(task.get("queue") or {})
                queue["position"] = position
                queue["limit"] = self._max_concurrency
                queue["active"] = active_now
                task["queue"] = queue
                task["updated_at"] = time.time()
                self._upsert_task_locked(task)

    def _upsert_task_locked(self, task: Dict[str, object]) -> None:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return
        payload_text = json.dumps(task, ensure_ascii=False)
        updated_at = float(task.get("updated_at") or 0)
        with self._db:
            self._db.execute(
                "REPLACE INTO tasks (id, updated_at, payload) VALUES (?, ?, ?)",
                (task_id, updated_at, payload_text),
            )

    def _delete_tasks_locked(self, task_ids: List[str]) -> None:
        ids = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
        if not ids:
            return
        with self._db:
            self._db.executemany("DELETE FROM tasks WHERE id = ?", ((task_id,) for task_id in ids))

    def _replace_all_tasks_locked(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM tasks")
            self._db.executemany(
                "REPLACE INTO tasks (id, updated_at, payload) VALUES (?, ?, ?)",
                (
                    (
                        str(task.get("id") or ""),
                        float(task.get("updated_at") or 0),
                        json.dumps(task, ensure_ascii=False),
                    )
                    for task in self._tasks.values()
                    if str(task.get("id") or "").strip()
                ),
            )

    def snapshot_task(self, task_id: str) -> TaskSnapshot:
        self._cleanup_tasks()
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"exists": False, "ok": False, "error": "task not found"}
            return build_task_snapshot(task)

    def submit_task(self, text: str) -> Dict[str, object]:
        self._cleanup_tasks()
        error = self._validate_input_text(text)
        if error:
            return {"ok": False, "error": error}
        queued_at = time.perf_counter()
        with self._queue_lock:
            self._pending += 1
            position = self._pending
            active_now = self._active
        task_id = self._create_task(text)
        self._update_task(task_id, queue={"position": position, "limit": self._max_concurrency, "active": active_now})
        self._refresh_queued_queue_state()

        def _run() -> None:
            started_at = time.perf_counter()
            with self._queue_lock:
                self._pending -= 1
                self._active += 1
                active_at_start = self._active
            self._refresh_queued_queue_state()
            self._update_task(
                task_id,
                queue={
                    "position": position,
                    "limit": self._max_concurrency,
                    "active_at_start": active_at_start,
                    "wait": self._format_seconds(started_at - queued_at),
                },
            )
            try:
                self._run_task(task_id, text, allow_cache=True)
            except Exception as exc:
                error_message = str(exc).strip() or "任务执行失败"
                if "模型ID、API密钥和服务地址必须被提供或在.env文件中定义" in error_message:
                    error_message = (
                        "缺少大模型配置：请在项目根目录创建 .env 并填写 "
                        "LLM_API_KEY、LLM_BASE_URL、LLM_MODEL_ID，"
                        "然后重启服务。"
                    )
                self._update_task(task_id, status="failed", error=error_message)
                self._append_progress(task_id, "失败", error_message)
                self._append_progress(task_id, "完成", "失败")
                self._logger.exception("task_crash id=%s", task_id)
            finally:
                with self._queue_lock:
                    self._active -= 1
                self._refresh_queued_queue_state()

        self._executor.submit(_run)
        return {"ok": True, "task_id": task_id, "queue": {"position": position, "limit": self._max_concurrency}}

    def _create_task(self, text: str) -> str:
        task_id = uuid.uuid4().hex
        now = time.time()
        task = {
            "id": task_id,
            "text": text,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "progress": [],
            "result": None,
            "error": "",
            "queue": {},
        }
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

    def _append_progress(self, task_id: str, label: str, detail: str = "") -> None:
        event = {"label": label, "time": time.strftime("%H:%M:%S", time.localtime())}
        if detail:
            safe = str(detail)
            safe = safe.encode("utf-8", "replace").decode("utf-8", "replace")
            safe = re.sub(r"[\x00-\x1F]", " ", safe)
            event["detail"] = safe
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["progress"].append(event)
            task["updated_at"] = time.time()
            self._upsert_task_locked(task)

    def _run_task(self, task_id: str, text: str, allow_cache: bool = True) -> None:
        started_at = time.perf_counter()
        self._logger.info("task_start id=%s text=%s", task_id, text)
        self._update_task(task_id, status="running")
        self._append_progress(task_id, "理解任务")

        def _llm_event(message: str) -> None:
            self._append_progress(task_id, "模型调用", message)

        text_clean = str(text or "").strip()
        explicit_single_person_input = _looks_like_person_atom(text_clean)
        story_dir = os.path.join(self._project_root(), "storymap", "examples", "story")
        try:
            known_people = set(story_person_names(story_dir))
        except Exception:
            known_people = set()
        try:
            known_authentic_people = set(known_authentic_person_names(story_dir=Path(story_dir)))
        except Exception:
            known_authentic_people = set(known_people)

        targets: List[str] = []
        targets_from_extraction = False
        if text_clean and text_clean in known_people:
            targets = [text_clean]
            self._append_progress(task_id, "识别任务对象", f"命中本地人物档案：{text_clean}")
        else:
            parts = [part.strip() for part in re.split(r"[、，,\s]+", text_clean) if part.strip()]
            if parts and all(part in known_people for part in parts) and len(parts) >= 2:
                targets = parts[:10]
                self._append_progress(task_id, "识别任务对象", f"命中本地人物档案：{'、'.join(targets)}")

        client: Optional[object] = None
        if not targets:
            client = self._get_llm_client(event_callback=_llm_event)
            targets = self._extract_historical_figures(client, text)
            targets_from_extraction = bool(targets)
        if not targets:
            fallback = str(text or "").strip()
            fallback_parts = [part.strip() for part in re.split(r"[、，,\s]+", fallback) if part.strip()]
            if len(fallback_parts) >= 2 and all(_looks_like_person_atom(part) for part in fallback_parts):
                targets = fallback_parts[:10]
                self._append_progress(task_id, "识别任务对象", f"未命中档案，已按输入人物列表处理：{'、'.join(targets)}")
            elif _looks_like_person_atom(fallback):
                targets = [fallback]
                self._append_progress(task_id, "识别任务对象", f"未命中档案，已按输入人物处理：{fallback}")
            else:
                error_message = "未识别到人物，请输入人物姓名，或先进入人物页再提问。"
                self._update_task(task_id, status="failed", error=error_message)
                self._append_progress(task_id, "失败", error_message)
                self._append_progress(task_id, "完成", "失败")
                self._logger.warning("task_failed id=%s error=%s", task_id, error_message)
                return

        resolved_targets = list(targets)
        blocked_targets = [
            person
            for person in targets
            if (
                not classify_story_person_authenticity(person, story_dir)[0]
                or (
                    targets_from_extraction
                    and not explicit_single_person_input
                    and person not in known_authentic_people
                )
            )
        ]
        blocked_results: List[Dict[str, object]] = []
        if blocked_targets:
            error_message = f"已拦截非真实或存疑人物：{'、'.join(blocked_targets[:3])}"
            self._append_progress(task_id, "真实性过滤", error_message)
            blocked_results = [
                {
                    "ok": False,
                    "status": "failed",
                    "person": person,
                    "error": f"已拦截非真实或存疑人物：{person}",
                }
                for person in blocked_targets
            ]
            allowed_targets = [person for person in targets if person not in blocked_targets]
            if not allowed_targets:
                self._update_task(task_id, status="failed", error=error_message)
                self._append_progress(task_id, "失败", error_message)
                self._append_progress(task_id, "完成", "失败")
                self._logger.warning("task_failed id=%s error=%s", task_id, error_message)
                return
            targets = allowed_targets

        generated_results = []
        people_payload = []
        for idx, person in enumerate(targets):
            def _progress(message: str) -> None:
                self._append_progress(task_id, message)

            result = self._generate_for_person(
                client,
                person,
                progress=_progress,
                allow_cache=allow_cache,
                event_callback=_llm_event,
                refresh_homepage=False,
            )
            generated_results.append(result)
            if _is_usable_result(result) and result.get("_profile"):
                profile = result.get("_profile") or {}
                export_allow_cache = allow_cache and (not bool(result.get("refreshed")))
                people_payload.append(
                    {
                        "person": profile.get("person", {}),
                        "locations": profile.get("locations", []),
                        "mapStyle": profile.get("mapStyle", {}),
                        "color": self._color_palette[idx % len(self._color_palette)],
                    }
                )
                result["exports"] = self._ensure_profile_exports(profile, person, allow_cache=export_allow_cache)

        results = list(blocked_results)
        results.extend(generated_results)

        overlaps = self._compute_overlaps(people_payload) if len(people_payload) > 1 else []
        multi_html_path = ""
        multi_exports: Dict[str, str] = {}
        if len(people_payload) > 1:
            self._append_progress(task_id, "生成合并视图")
            title = "多人物合并视图"
            multi_data = {"title": title, "people": people_payload, "overlaps": overlaps}
            multi_html = self._render_multi_html(multi_data)
            multi_name = f"{title}_{task_id[:8]}"
            multi_html_path = self._save_html(multi_name, multi_html)
            multi_exports = self._ensure_multi_exports(people_payload, multi_name, allow_cache=allow_cache)

        duration = self._format_seconds(time.perf_counter() - started_at)
        conclusion = self._build_conclusion(results, len(people_payload) > 1)
        success_results = [result for result in results if _is_usable_result(result) and not _has_task_blocking_failure(result)]
        failed_results = [result for result in results if (not _is_usable_result(result)) or _has_task_blocking_failure(result)]
        failed_people = [str(item.get("person") or "").strip() for item in failed_results if str(item.get("person") or "").strip()]
        if success_results and failed_results:
            summary_status = "partial_failed"
        elif success_results:
            summary_status = "completed"
        else:
            summary_status = "failed"
        files: List[TaskFileEntry] = []
        for result in results:
            if not _is_usable_result(result):
                continue
            file_entry: TaskFileEntry = {
                "markdown": self._relative_path(result.get("markdown_path", "")),
                "html": self._relative_path(result.get("html_path", "")),
            }
            exports = result.get("exports") or {}
            if exports.get("geojson"):
                file_entry["geojson"] = self._relative_path(exports.get("geojson", ""))
            if exports.get("csv"):
                file_entry["csv"] = self._relative_path(exports.get("csv", ""))
            files.append(file_entry)
        multi_entry: Optional[TaskMultiEntry] = None
        if multi_html_path:
            multi_entry = {
                "html": self._relative_path(multi_html_path),
                "geojson": self._relative_path(multi_exports.get("geojson", "")) if multi_exports else "",
                "csv": self._relative_path(multi_exports.get("csv", "")) if multi_exports else "",
            }
        summary: TaskResultSummary = build_task_result_summary(
            ok=(summary_status == "completed"),
            status=summary_status,
            people=resolved_targets,
            results=results,
            success_count=len(success_results),
            failed_count=len(failed_results),
            failed_people=failed_people,
            multi_html_path=multi_html_path,
            multi_exports=multi_exports,
            overlaps=overlaps,
            duration=duration,
            conclusion=conclusion,
            files=files,
            meta=_collect_result_runtime_meta(results),
            multi=multi_entry,
        )
        self._append_progress(task_id, "输出结论")
        if summary_status == "failed":
            errors = []
            for result in results:
                message = str(result.get("error") or "").strip()
                if message and message not in errors:
                    errors.append(message)
            error_message = "；".join(errors[:3]) or "未生成成功"
            self._update_task(task_id, status="failed", error=error_message, result=summary)
            self._append_progress(task_id, "失败", error_message)
            self._append_progress(task_id, "完成", "失败")
            self._logger.warning("task_failed id=%s error=%s", task_id, error_message)
            return
        if summary_status == "partial_failed":
            errors = []
            for result in failed_results:
                message = str(result.get("error") or "").strip()
                if message and message not in errors:
                    errors.append(message)
            error_message = "；".join(errors[:3]) or f"部分人物生成失败：{'、'.join(failed_people[:3])}"
            self._update_task(task_id, status="partial_failed", error=error_message, result=summary)
            self._append_progress(task_id, "部分失败", error_message)
            self._append_progress(task_id, "完成", "部分失败")
            self._logger.warning("task_partial_failed id=%s error=%s", task_id, error_message)
            return
        self._update_task(task_id, status="completed", result=summary)
        self._logger.info("task_completed id=%s duration=%s", task_id, duration)
