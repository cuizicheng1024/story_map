from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional


class TaskArchiveRefresher:
    def __init__(
        self,
        *,
        logger: object,
        refresh_stellar_homepage: Optional[Callable[[str], Dict[str, object]]],
        enqueue_background_job: Optional[Callable[..., object]],
        archive_executor: ThreadPoolExecutor,
        can_continue: Callable[[str], bool],
        update_archive: Callable[[str, Dict[str, object]], None],
        append_progress: Callable[[str, str, str], None],
    ) -> None:
        self._logger = logger
        self._refresh_stellar_homepage = refresh_stellar_homepage
        self._enqueue_background_job = enqueue_background_job
        self._archive_executor = archive_executor
        self._can_continue = can_continue
        self._update_archive = update_archive
        self._append_progress = append_progress

    def enqueue(self, task_id: str, people: List[str], *, shutting_down: bool = False) -> None:
        targets = [str(item).strip() for item in list(people or []) if str(item).strip()]
        if not targets or not callable(self._refresh_stellar_homepage):
            return
        if shutting_down or (not self._can_continue(task_id)):
            return
        queued_archive = {
            "state": "queued",
            "label": "排队中",
            "people": targets,
            "visible": False,
        }
        self._update_archive(task_id, queued_archive)
        self._append_progress(task_id, "后台归档", f"人物页已生成，群星首页与知识图谱将在后台补齐：{'、'.join(targets[:3])}")

        def _run_archive() -> None:
            if not self._can_continue(task_id):
                return
            running_archive = {
                "state": "running",
                "label": "归档中",
                "people": targets,
                "visible": False,
            }
            self._update_archive(task_id, running_archive)
            self._append_progress(task_id, "后台归档", "正在刷新群星首页与知识图谱")
            try:
                refresh_result = self._refresh_stellar_homepage(targets[0]) or {}
                payload = dict(refresh_result or {}) if isinstance(refresh_result, dict) else {}
                ok = bool(payload.get("ok"))
                archive_payload = {
                    "state": "completed" if ok else "failed",
                    "label": "已归档" if ok else "归档失败",
                    "people": targets,
                    "visible": bool(ok),
                    "detail": str(payload.get("output") or payload.get("error") or "").strip(),
                    "updated_at": time.time(),
                }
                if payload.get("index_path"):
                    archive_payload["index_path"] = str(payload.get("index_path") or "")
                if payload.get("data_path"):
                    archive_payload["data_path"] = str(payload.get("data_path") or "")
                self._update_archive(task_id, archive_payload)
                if ok:
                    self._append_progress(task_id, "后台归档", "群星首页与知识图谱已补齐，现在重新打开首页即可看到")
                else:
                    self._append_progress(task_id, "后台归档", archive_payload["detail"] or "群星首页与知识图谱后台补齐失败")
            except Exception as exc:
                detail = str(exc).strip() or "群星首页与知识图谱后台补齐失败"
                self._update_archive(
                    task_id,
                    {
                        "state": "failed",
                        "label": "归档失败",
                        "people": targets,
                        "visible": False,
                        "detail": detail,
                        "updated_at": time.time(),
                    },
                )
                self._append_progress(task_id, "后台归档", detail)
                self._logger.warning("task_archive_failed id=%s people=%s error=%s", task_id, ",".join(targets), detail)

        try:
            submit_result: object
            if callable(self._enqueue_background_job):
                submit_result = self._enqueue_background_job(
                    _run_archive,
                    label=f"task-archive:{task_id}",
                    metadata={"task_id": task_id, "people": targets, "kind": "task_archive"},
                )
            else:
                self._archive_executor.submit(_run_archive)
                submit_result = True
            if isinstance(submit_result, dict):
                accepted = bool(
                    submit_result.get("queued", submit_result.get("accepted", submit_result.get("ok", True)))
                )
            else:
                accepted = bool(submit_result)
            if accepted:
                return
            detail = "后台归档任务未能进入队列"
        except Exception as exc:
            detail = str(exc).strip() or "后台归档任务未能进入队列"
        self._update_archive(
            task_id,
            {
                "state": "failed",
                "label": "归档失败",
                "people": targets,
                "visible": False,
                "detail": detail,
                "updated_at": time.time(),
            },
        )
        self._append_progress(task_id, "后台归档", detail)
        self._logger.warning("task_archive_enqueue_failed id=%s people=%s error=%s", task_id, ",".join(targets), detail)


__all__ = ["TaskArchiveRefresher"]
