import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, Tuple, Type


def normalize_crash_error_message(error_message: str) -> str:
    message = str(error_message or "").strip() or "任务执行失败"
    if "模型ID、API密钥和服务地址必须被提供或在.env文件中定义" in message:
        return (
            "缺少大模型配置：请在项目根目录创建 .env 并填写 "
            "LLM_API_KEY、LLM_BASE_URL、LLM_MODEL_ID，"
            "然后重启服务。"
        )
    return message


class TaskExecutionCoordinator:
    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor,
        max_concurrency: int,
        format_seconds: Callable[[float], str],
        task_timeout_seconds: int,
        logger: object,
        reserve_queue_slot: Callable[[], Tuple[int, int]],
        activate_queue_slot: Callable[[], int],
        release_active_slot: Callable[[], None],
        refresh_queued_queue_state: Callable[[], None],
        register_future: Callable[[str, Future[None]], None],
        unregister_future: Callable[[str], None],
        update_task: Callable[..., None],
        append_progress: Callable[[str, str, str], None],
        record_metrics: Callable[..., None],
        ensure_task_can_continue: Callable[[str], None],
        run_task: Callable[[str, str, bool], None],
    ) -> None:
        self._executor = executor
        self._max_concurrency = int(max_concurrency)
        self._format_seconds = format_seconds
        self._task_timeout_seconds = int(task_timeout_seconds)
        self._logger = logger
        self._reserve_queue_slot = reserve_queue_slot
        self._activate_queue_slot = activate_queue_slot
        self._release_active_slot = release_active_slot
        self._refresh_queued_queue_state = refresh_queued_queue_state
        self._register_future = register_future
        self._unregister_future = unregister_future
        self._update_task = update_task
        self._append_progress = append_progress
        self._record_metrics = record_metrics
        self._ensure_task_can_continue = ensure_task_can_continue
        self._run_task = run_task

    def submit(
        self,
        *,
        task_id: str,
        text: str,
        cancelled_exc_type: Type[BaseException],
        timed_out_exc_type: Type[BaseException],
    ) -> Dict[str, object]:
        queued_at = time.perf_counter()
        position, active_now = self._reserve_queue_slot()
        self._update_task(
            task_id,
            queue={"position": position, "limit": self._max_concurrency, "active": active_now},
        )
        self._refresh_queued_queue_state()

        def _run() -> None:
            started_at = time.perf_counter()
            active_at_start = self._activate_queue_slot()
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
                self._record_metrics(queue_wait_seconds_total=max(0.0, started_at - queued_at))
                self._ensure_task_can_continue(task_id)
                self._run_task(task_id, text, True)
            except cancelled_exc_type as exc:
                message = str(exc).strip() or "任务已取消。"
                self._update_task(task_id, status="cancelled", error=message)
                self._append_progress(task_id, "取消", message)
                self._append_progress(task_id, "完成", "已取消")
                self._record_metrics(
                    cancelled=1,
                    duration_seconds_total=max(0.0, time.perf_counter() - started_at),
                )
                self._logger.warning("task_cancelled id=%s error=%s", task_id, message)
            except timed_out_exc_type as exc:
                message = str(exc).strip() or f"任务执行超时，已超过 {self._task_timeout_seconds} 秒。"
                self._update_task(task_id, status="timed_out", error=message)
                self._append_progress(task_id, "超时", message)
                self._append_progress(task_id, "完成", "超时")
                self._record_metrics(
                    timed_out=1,
                    duration_seconds_total=max(0.0, time.perf_counter() - started_at),
                )
                self._logger.warning("task_timed_out id=%s error=%s", task_id, message)
            except Exception as exc:
                error_message = normalize_crash_error_message(str(exc))
                self._update_task(task_id, status="failed", error=error_message)
                self._append_progress(task_id, "失败", error_message)
                self._append_progress(task_id, "完成", "失败")
                self._record_metrics(
                    crashed=1,
                    failed=1,
                    duration_seconds_total=max(0.0, time.perf_counter() - started_at),
                )
                self._logger.exception("task_crash id=%s", task_id)
            finally:
                self._release_active_slot()
                self._refresh_queued_queue_state()
                self._unregister_future(task_id)

        future = self._executor.submit(_run)
        self._register_future(task_id, future)
        return {
            "ok": True,
            "task_id": task_id,
            "queue": {"position": position, "limit": self._max_concurrency},
        }
