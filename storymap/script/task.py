import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple


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

        self._executor = ThreadPoolExecutor(max_workers=max_concurrency)
        self._queue_lock = threading.Lock()
        self._pending = 0
        self._active = 0
        self._task_lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, object]] = {}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def snapshot_task(self, task_id: str) -> Dict[str, object]:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"ok": False, "error": "task not found"}
            return {"ok": True, **task}

    def submit_task(self, text: str) -> Dict[str, object]:
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
        return task_id

    def _update_task(self, task_id: str, **fields: object) -> None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(fields)
            task["updated_at"] = time.time()

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

    def _run_task(self, task_id: str, text: str, allow_cache: bool = True) -> None:
        started_at = time.perf_counter()
        self._logger.info("task_start id=%s text=%s", task_id, text)
        self._update_task(task_id, status="running")
        self._append_progress(task_id, "人物识别")

        def _llm_event(message: str) -> None:
            self._append_progress(task_id, "模型日志", message)

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
            self._append_progress(task_id, "人物识别", f"命中本地人物：{text_clean}")
        else:
            parts = [part.strip() for part in re.split(r"[、，,\s]+", text_clean) if part.strip()]
            if parts and all(part in known_people for part in parts) and len(parts) >= 2:
                targets = parts[:10]
                self._append_progress(task_id, "人物识别", f"命中本地人物：{'、'.join(targets)}")

        client: Optional[object] = None
        if not targets:
            client = self._get_llm_client(event_callback=_llm_event)
            targets = self._extract_historical_figures(client, text)
        if not targets:
            fallback = str(text or "").strip()
            if fallback:
                targets = [fallback]
                self._append_progress(task_id, "人物识别", f"未检出列表，已按输入人物处理：{fallback}")
            else:
                error_message = "未识别到人物"
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
            self._append_progress(task_id, "合并视图渲染")
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
        self._append_progress(task_id, "完成")
        self._update_task(task_id, status="completed", result=summary)
        self._logger.info("task_completed id=%s duration=%s", task_id, duration)
