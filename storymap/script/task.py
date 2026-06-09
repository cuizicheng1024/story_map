import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple


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


def _looks_like_person_atom(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) > 12:
        return False
    if re.search(r"[?？!！。:：；;（）()\[\]{}<>]", cleaned):
        return False
    return not any(token in cleaned for token in _TASK_LIKE_TOKENS)


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
        self._state_path = os.path.join(self._project_root(), "artifacts", "runtime", "task_state.json")
        self._load_tasks_from_disk()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def _load_tasks_from_disk(self) -> None:
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return
        except Exception as exc:
            self._logger.warning("task_state_load_failed path=%s error=%s", self._state_path, exc)
            return
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list):
            return
        recovered: Dict[str, Dict[str, object]] = {}
        now = time.time()
        for item in tasks:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("id") or "").strip()
            if not task_id:
                continue
            task = dict(item)
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
            recovered[task_id] = task
        with self._task_lock:
            self._tasks = recovered
            self._trim_tasks_locked()
            self._persist_tasks_locked()

    def _persist_tasks_locked(self) -> None:
        parent = os.path.dirname(self._state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"tasks": list(self._tasks.values())}
        tmp_path = f"{self._state_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._state_path)

    def snapshot_task(self, task_id: str) -> Dict[str, object]:
        self._cleanup_tasks()
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"ok": False, "error": "task not found"}
            return {"ok": True, **task}

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

        def _run() -> None:
            started_at = time.perf_counter()
            with self._queue_lock:
                self._pending -= 1
                self._active += 1
                active_at_start = self._active
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
                        "LLM_API_KEY、LLM_BASE_URL、LLM_MODEL_ID（或 MINIMAX_API_KEY/MINIMAX_BASE_URL/MINIMAX_MODEL），"
                        "然后重启服务。"
                    )
                self._update_task(task_id, status="failed", error=error_message)
                self._append_progress(task_id, "失败", error_message)
                self._append_progress(task_id, "完成", "失败")
                self._logger.exception("task_crash id=%s", task_id)
            finally:
                with self._queue_lock:
                    self._active -= 1

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
            self._trim_tasks_locked()
            self._persist_tasks_locked()
        return task_id

    def _cleanup_tasks(self) -> None:
        cutoff = time.time() - self._task_ttl_seconds
        with self._task_lock:
            expired_ids = [
                task_id
                for task_id, task in self._tasks.items()
                if task.get("status") in {"completed", "failed"}
                and float(task.get("updated_at") or 0) < cutoff
            ]
            for task_id in expired_ids:
                self._tasks.pop(task_id, None)
            self._trim_tasks_locked()
            self._persist_tasks_locked()

    def _trim_tasks_locked(self) -> None:
        overflow = len(self._tasks) - self._max_tasks
        if overflow <= 0:
            return
        # 优先丢弃已结束且最久未更新的任务，避免运行中的任务被提前清理。
        ordered = sorted(
            self._tasks.items(),
            key=lambda item: (
                item[1].get("status") not in {"completed", "failed"},
                float(item[1].get("updated_at") or 0),
            ),
        )
        for task_id, task in ordered:
            if overflow <= 0:
                break
            if task.get("status") in {"queued", "running"}:
                continue
            self._tasks.pop(task_id, None)
            overflow -= 1

    def _update_task(self, task_id: str, **fields: object) -> None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(fields)
            task["updated_at"] = time.time()
            self._trim_tasks_locked()
            self._persist_tasks_locked()

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
            self._persist_tasks_locked()

    def _run_task(self, task_id: str, text: str, allow_cache: bool = True) -> None:
        started_at = time.perf_counter()
        self._logger.info("task_start id=%s text=%s", task_id, text)
        self._update_task(task_id, status="running")
        self._append_progress(task_id, "理解任务")

        def _llm_event(message: str) -> None:
            self._append_progress(task_id, "模型调用", message)

        text_clean = str(text or "").strip()
        story_dir = os.path.join(self._project_root(), "storymap", "examples", "story")
        known_people = set()
        try:
            for entry in os.listdir(story_dir):
                if entry.endswith(".md"):
                    stem = os.path.splitext(entry)[0].strip()
                    if stem:
                        known_people.add(stem)
        except Exception:
            known_people = set()

        targets: List[str] = []
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

        results = []
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
            )
            results.append(result)
            if result.get("ok") and result.get("_profile"):
                profile = result.get("_profile") or {}
                people_payload.append(
                    {
                        "person": profile.get("person", {}),
                        "locations": profile.get("locations", []),
                        "mapStyle": profile.get("mapStyle", {}),
                        "color": self._color_palette[idx % len(self._color_palette)],
                    }
                )
                result["exports"] = self._ensure_profile_exports(profile, person, allow_cache=allow_cache)

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
        summary: Dict[str, object] = {
            "ok": any(result.get("ok") for result in results),
            "people": targets,
            "results": results,
            "multi_html_path": multi_html_path,
            "multi_exports": multi_exports,
            "overlaps": overlaps,
            "duration": duration,
            "conclusion": conclusion,
            "files": [],
        }
        for result in results:
            if not result.get("ok"):
                continue
            files = {
                "markdown": self._relative_path(result.get("markdown_path", "")),
                "html": self._relative_path(result.get("html_path", "")),
            }
            exports = result.get("exports") or {}
            if exports.get("geojson"):
                files["geojson"] = self._relative_path(exports.get("geojson", ""))
            if exports.get("csv"):
                files["csv"] = self._relative_path(exports.get("csv", ""))
            summary["files"].append(files)
        if multi_html_path:
            summary["multi"] = {
                "html": self._relative_path(multi_html_path),
                "geojson": self._relative_path(multi_exports.get("geojson", "")) if multi_exports else "",
                "csv": self._relative_path(multi_exports.get("csv", "")) if multi_exports else "",
            }
        self._append_progress(task_id, "输出结论")
        self._update_task(task_id, status="completed", result=summary)
        self._logger.info("task_completed id=%s duration=%s", task_id, duration)
