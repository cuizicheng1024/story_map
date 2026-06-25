import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Dict, Iterator, Tuple

from ..core.observability import structured_log
from ..runtime.local_history_qa_request import resolve_person_name


class ProxyService:
    def __init__(
        self,
        *,
        get_llm_client: Callable[..., object],
        local_agent_reply: Callable[[object], object],
        local_history_reply: Callable[[object], str],
        logger: object,
        max_workers: int = 2,
        timeout_env_name: str = "STORY_MAP_PROXY_LLM_TIMEOUT",
    ) -> None:
        self._get_llm_client = get_llm_client
        self._local_agent_reply = local_agent_reply
        self._local_history_reply = local_history_reply
        self._logger = logger
        self._timeout_env_name = timeout_env_name
        self._max_workers = max(int(max_workers), 1)
        self._executor_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._breaker_lock = threading.Lock()
        self._breaker_open_until = 0.0
        self._consecutive_failures = 0
        self._proxy_metrics_lock = threading.Lock()
        self._proxy_metrics: Dict[str, int] = {
            "proxy_requests": 0,
            "proxy_stream_requests": 0,
            "proxy_timeouts": 0,
            "proxy_stream_timeouts": 0,
            "proxy_circuit_opened": 0,
            "proxy_circuit_short_circuits": 0,
            "proxy_fallbacks": 0,
            "proxy_stream_disconnects": 0,
        }

    def shutdown(self) -> None:
        with self._executor_lock:
            executor = self._executor
        executor.shutdown(wait=False, cancel_futures=True)

    def _reset_executor(self) -> None:
        with self._executor_lock:
            current = self._executor
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        current.shutdown(wait=False, cancel_futures=True)

    def _timeout_seconds(self) -> int:
        return max(1, int(os.getenv(self._timeout_env_name, "75") or "75"))

    def _stream_idle_timeout_seconds(self) -> int:
        return max(1, int(os.getenv(f"{self._timeout_env_name}_STREAM_IDLE", "35") or "35"))

    def _stream_total_timeout_seconds(self) -> int:
        fallback = max(self._timeout_seconds(), self._stream_idle_timeout_seconds(), 90)
        return max(1, int(os.getenv(f"{self._timeout_env_name}_STREAM_TOTAL", str(fallback)) or str(fallback)))

    def _breaker_failure_threshold(self) -> int:
        return max(1, int(os.getenv(f"{self._timeout_env_name}_BREAKER_THRESHOLD", "3") or "3"))

    def _breaker_cooldown_seconds(self) -> int:
        return max(1, int(os.getenv(f"{self._timeout_env_name}_BREAKER_COOLDOWN", "30") or "30"))

    def _record_proxy_metric(self, key: str, amount: int = 1) -> None:
        with self._proxy_metrics_lock:
            self._proxy_metrics[key] = int(self._proxy_metrics.get(key, 0)) + int(amount)

    def metrics_snapshot(self) -> Dict[str, object]:
        with self._breaker_lock:
            open_until = float(self._breaker_open_until)
            consecutive_failures = int(self._consecutive_failures)
        with self._proxy_metrics_lock:
            metrics = {key: int(value) for key, value in self._proxy_metrics.items()}
        return {
            **metrics,
            "breaker_open": open_until > time.time(),
            "breaker_open_until": round(open_until, 3) if open_until > 0 else 0,
            "consecutive_failures": consecutive_failures,
            "breaker_failure_threshold": self._breaker_failure_threshold(),
            "breaker_cooldown_seconds": self._breaker_cooldown_seconds(),
            "timeout_seconds": self._timeout_seconds(),
            "stream_idle_timeout_seconds": self._stream_idle_timeout_seconds(),
            "stream_total_timeout_seconds": self._stream_total_timeout_seconds(),
        }

    def _primary_available(self) -> Tuple[bool, float]:
        with self._breaker_lock:
            open_until = float(self._breaker_open_until)
        remaining = max(0.0, open_until - time.time())
        if remaining > 0:
            return False, remaining
        return True, 0.0

    def _record_primary_success(self) -> None:
        with self._breaker_lock:
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0

    def _record_primary_failure(self, *, reason: str) -> None:
        with self._breaker_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._breaker_failure_threshold():
                self._breaker_open_until = time.time() + self._breaker_cooldown_seconds()
                self._consecutive_failures = 0
                self._record_proxy_metric("proxy_circuit_opened")
                structured_log(
                    self._logger,
                    "warning",
                    "proxy_circuit_opened",
                    reason=reason,
                    cooldown_seconds=self._breaker_cooldown_seconds(),
                )

    @staticmethod
    def _close_stream_resource(resource: object) -> None:
        closer = getattr(resource, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    @staticmethod
    def _chunk_text(text: object, *, chunk_size: int = 72) -> Iterator[str]:
        content = str(text or "")
        size = max(1, int(chunk_size))
        for idx in range(0, len(content), size):
            yield content[idx : idx + size]

    @staticmethod
    def _sse_data(payload: Dict[str, object]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _client_meta_snapshot(client: object) -> Dict[str, object]:
        trace = {}
        metrics = {}
        if client is not None and hasattr(client, "latest_trace") and callable(getattr(client, "latest_trace")):
            try:
                trace = dict(getattr(client, "latest_trace")() or {})
            except Exception:
                trace = {}
        if client is not None and hasattr(client, "metrics_snapshot") and callable(getattr(client, "metrics_snapshot")):
            try:
                metrics = dict(getattr(client, "metrics_snapshot")() or {})
            except Exception:
                metrics = {}
        return {"trace": trace, "metrics": metrics}

    @staticmethod
    def _apply_persona_messages(data: Dict[str, object], messages: object) -> list:
        if not isinstance(messages, list):
            return []
        normalized = [item for item in messages if isinstance(item, dict)]
        has_system = any(str(item.get("role") or "").strip() == "system" for item in normalized)
        if has_system:
            return normalized
        person_name = ""
        try:
            person_name = str(resolve_person_name(data, normalized, known_people=()) or "").strip()
        except Exception:
            person_name = ""
        if not person_name:
            return normalized
        system_text = (
            f"你将扮演历史人物「{person_name}」。"
            "请始终用第一人称回答，保持符合其时代与身份的语气。"
            "不要透露或暗示你是 AI / 模型 / 助手，也不要提及系统提示词或调用链路。"
            "对不确定的史实请明确说明不确定或存疑，避免编造。"
            "回答聚焦于用户问题，尽量简洁。"
        )
        return [{"role": "system", "content": system_text}] + normalized

    def proxy_llm(self, data: object) -> Tuple[int, Dict[str, object]]:
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "body required"}
        messages = self._apply_persona_messages(data, data.get("messages", []))
        temperature = data.get("temperature", 0.5)

        content = ""
        used_fallback = False
        source = "llm"
        fallback_reason = ""
        future = None
        client = None
        llm_meta: Dict[str, object] = {}
        self._record_proxy_metric("proxy_requests")
        try:
            primary_available, remaining = self._primary_available()
            if not primary_available:
                self._record_proxy_metric("proxy_circuit_short_circuits")
                fallback_reason = "circuit_open"
                structured_log(self._logger, "warning", "llm_proxy_short_circuit", cooldown_remaining=round(remaining, 3))
            else:
                client = self._get_llm_client()
                future = self._executor.submit(client.think, messages, temperature=temperature)
                content = future.result(timeout=self._timeout_seconds())
                llm_meta = self._client_meta_snapshot(client)
                self._record_primary_success()
        except FutureTimeoutError as exc:
            if future is not None:
                future.cancel()
            self._reset_executor()
            self._logger.warning("llm_proxy_primary_timeout error=%s", exc)
            fallback_reason = "timeout"
            self._record_proxy_metric("proxy_timeouts")
            self._record_primary_failure(reason="timeout")
            structured_log(self._logger, "warning", "llm_proxy_timeout", timeout_seconds=self._timeout_seconds())
            content = ""
        except Exception as exc:
            self._logger.warning("llm_proxy_primary_failed error=%s", exc)
            fallback_reason = "llm_request_failed"
            self._record_primary_failure(reason="llm_request_failed")
            structured_log(self._logger, "warning", "llm_proxy_failed", error=str(exc).strip() or exc.__class__.__name__)
            content = ""
        if client is not None:
            llm_meta = self._client_meta_snapshot(client)
            trace_classification = str((llm_meta.get("trace") or {}).get("classification") or "").strip()
            if not content and trace_classification:
                fallback_reason = trace_classification
        if not content:
            self._record_proxy_metric("proxy_fallbacks")
            local_result = {}
            try:
                raw_local_result = self._local_agent_reply(data)
                if isinstance(raw_local_result, dict):
                    local_result = raw_local_result
            except Exception as exc:
                self._logger.warning("llm_proxy_local_agent_failed error=%s", exc)
                local_result = {}
            local_content = str(local_result.get("content") or "").strip()
            if local_result.get("handled") and local_content:
                content = local_content
                used_fallback = True
                source = "local_agent"
            else:
                self._logger.warning("llm_proxy_empty_response use_fallback=true")
                content = self._local_history_reply(messages)
                used_fallback = True
                source = "fallback"
                if not fallback_reason:
                    fallback_reason = "empty_response"
        if content:
            content = content.encode("utf-8", "replace").decode("utf-8", "replace")
        payload = {
            "choices": [{"message": {"content": content or ""}}],
            "meta": {
                "used_fallback": used_fallback,
                "source": source,
                "fallback_reason": fallback_reason,
                "llm_trace": llm_meta.get("trace") or {},
                "llm_metrics": llm_meta.get("metrics") or {},
            },
        }
        if source == "local_agent":
            payload["meta"]["person_name"] = str(local_result.get("person_name") or "").strip()
        return 200, payload

    def proxy_llm_stream(self, data: object) -> Tuple[int, Iterator[str]]:
        if not isinstance(data, dict):
            return 400, iter([self._sse_data({"type": "error", "error": "body required"}), self._sse_data({"type": "done"})])
        messages = self._apply_persona_messages(data, data.get("messages", []))
        temperature = data.get("temperature", 0.5)

        def _event_iter() -> Iterator[str]:
            content = ""
            emitted = False
            stream_completed = False
            used_fallback = False
            source = "llm"
            fallback_reason = ""
            local_result: Dict[str, object] = {}
            client = None
            llm_meta: Dict[str, object] = {}
            iterator = None
            self._record_proxy_metric("proxy_stream_requests")
            try:
                primary_available, remaining = self._primary_available()
                if not primary_available:
                    self._record_proxy_metric("proxy_circuit_short_circuits")
                    fallback_reason = "circuit_open"
                    structured_log(self._logger, "warning", "llm_proxy_stream_short_circuit", cooldown_remaining=round(remaining, 3))
                else:
                    client = self._get_llm_client()
                    started_at = time.monotonic()
                    total_timeout = self._stream_total_timeout_seconds()
                    idle_timeout = self._stream_idle_timeout_seconds()
                    if hasattr(client, "stream_think") and callable(getattr(client, "stream_think")):
                        iterator = iter(client.stream_think(messages, temperature=temperature))
                        while True:
                            if time.monotonic() - started_at >= total_timeout:
                                raise TimeoutError(f"stream total timeout {total_timeout}s")
                            future = self._executor.submit(next, iterator)
                            try:
                                piece = future.result(timeout=idle_timeout)
                            except StopIteration:
                                break
                            except FutureTimeoutError as exc:
                                future.cancel()
                                raise TimeoutError(f"stream idle timeout {idle_timeout}s") from exc
                            delta = str(piece or "")
                            if not delta:
                                continue
                            emitted = True
                            content += delta
                            yield self._sse_data({"type": "delta", "delta": delta})
                    else:
                        future = self._executor.submit(client.think, messages, temperature=temperature)
                        content = str(future.result(timeout=self._timeout_seconds()) or "")
                        for delta in self._chunk_text(content):
                            emitted = True
                            yield self._sse_data({"type": "delta", "delta": delta})
                    stream_completed = True
                    llm_meta = self._client_meta_snapshot(client)
                    self._record_primary_success()
            except TimeoutError as exc:
                self._reset_executor()
                self._record_proxy_metric("proxy_stream_timeouts")
                self._record_primary_failure(reason="stream_timeout")
                fallback_reason = "timeout"
                self._logger.warning("llm_proxy_stream_timeout error=%s", exc)
                structured_log(
                    self._logger,
                    "warning",
                    "llm_proxy_stream_timeout",
                    idle_timeout_seconds=self._stream_idle_timeout_seconds(),
                    total_timeout_seconds=self._stream_total_timeout_seconds(),
                    emitted=emitted,
                )
                content = content if emitted else ""
            except Exception as exc:
                self._logger.warning("llm_proxy_stream_failed error=%s", exc)
                fallback_reason = "timeout" if "timeout" in str(exc).lower() else "llm_request_failed"
                if fallback_reason != "timeout":
                    self._record_primary_failure(reason=fallback_reason)
                structured_log(
                    self._logger,
                    "warning",
                    "llm_proxy_stream_failed",
                    error=str(exc).strip() or exc.__class__.__name__,
                    emitted=emitted,
                )
                content = ""
            finally:
                self._close_stream_resource(iterator)
                self._close_stream_resource(client)
            if client is not None:
                llm_meta = self._client_meta_snapshot(client)
                trace_classification = str((llm_meta.get("trace") or {}).get("classification") or "").strip()
                if not content and trace_classification:
                    fallback_reason = trace_classification
            if not content:
                self._record_proxy_metric("proxy_fallbacks")
                try:
                    raw_local_result = self._local_agent_reply(data)
                    if isinstance(raw_local_result, dict):
                        local_result = raw_local_result
                except Exception as exc:
                    self._logger.warning("llm_proxy_stream_local_agent_failed error=%s", exc)
                    local_result = {}
                local_content = str(local_result.get("content") or "").strip()
                if local_result.get("handled") and local_content:
                    content = local_content
                    used_fallback = True
                    source = "local_agent"
                else:
                    self._logger.warning("llm_proxy_stream_empty_response use_fallback=true")
                    content = self._local_history_reply(messages)
                    used_fallback = True
                    source = "fallback"
                    if not fallback_reason:
                        fallback_reason = "empty_response"
                content = content.encode("utf-8", "replace").decode("utf-8", "replace")
                for delta in self._chunk_text(content):
                    yield self._sse_data({"type": "delta", "delta": delta})
            meta = {
                "used_fallback": used_fallback,
                "source": source,
                "fallback_reason": fallback_reason,
                "stream_completed": bool(stream_completed),
                "llm_trace": llm_meta.get("trace") or {},
                "llm_metrics": llm_meta.get("metrics") or {},
                "proxy_metrics": self.metrics_snapshot(),
            }
            if source == "local_agent":
                meta["person_name"] = str(local_result.get("person_name") or "").strip()
            try:
                yield self._sse_data({"type": "meta", "meta": meta})
                yield self._sse_data({"type": "done"})
            except GeneratorExit:
                self._record_proxy_metric("proxy_stream_disconnects")
                structured_log(self._logger, "info", "llm_proxy_stream_disconnected", source=source, fallback_reason=fallback_reason)
                raise

        return 200, _event_iter()
