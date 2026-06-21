import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Dict, Iterator, Tuple


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

    def shutdown(self) -> None:
        with self._executor_lock:
            executor = self._executor
        executor.shutdown(wait=False, cancel_futures=True)

    def _reset_executor(self) -> None:
        with self._executor_lock:
            current = self._executor
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        current.shutdown(wait=False, cancel_futures=True)

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

    def proxy_llm(self, data: object) -> Tuple[int, Dict[str, object]]:
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "body required"}
        messages = data.get("messages", [])
        temperature = data.get("temperature", 0.5)

        content = ""
        used_fallback = False
        source = "llm"
        fallback_reason = ""
        future = None
        client = None
        llm_meta: Dict[str, object] = {}
        try:
            client = self._get_llm_client()
            future = self._executor.submit(client.think, messages, temperature=temperature)
            timeout_s = max(1, int(os.getenv(self._timeout_env_name, "60") or "60"))
            content = future.result(timeout=timeout_s)
            llm_meta = self._client_meta_snapshot(client)
        except FutureTimeoutError as exc:
            if future is not None:
                future.cancel()
            self._reset_executor()
            self._logger.warning("llm_proxy_primary_timeout error=%s", exc)
            fallback_reason = "timeout"
            content = ""
        except Exception as exc:
            self._logger.warning("llm_proxy_primary_failed error=%s", exc)
            fallback_reason = "llm_request_failed"
            content = ""
        if client is not None:
            llm_meta = self._client_meta_snapshot(client)
            trace_classification = str((llm_meta.get("trace") or {}).get("classification") or "").strip()
            if not content and trace_classification:
                fallback_reason = trace_classification
        if not content:
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
        messages = data.get("messages", [])
        temperature = data.get("temperature", 0.5)

        def _event_iter() -> Iterator[str]:
            content = ""
            used_fallback = False
            source = "llm"
            fallback_reason = ""
            local_result: Dict[str, object] = {}
            client = None
            llm_meta: Dict[str, object] = {}
            try:
                client = self._get_llm_client()
                if hasattr(client, "stream_think") and callable(getattr(client, "stream_think")):
                    for piece in client.stream_think(messages, temperature=temperature):
                        delta = str(piece or "")
                        if not delta:
                            continue
                        content += delta
                        yield self._sse_data({"type": "delta", "delta": delta})
                else:
                    content = str(client.think(messages, temperature=temperature) or "")
                    for delta in self._chunk_text(content):
                        yield self._sse_data({"type": "delta", "delta": delta})
                llm_meta = self._client_meta_snapshot(client)
            except Exception as exc:
                self._logger.warning("llm_proxy_stream_failed error=%s", exc)
                fallback_reason = "timeout" if "timeout" in str(exc).lower() else "llm_request_failed"
                content = ""
            if client is not None:
                llm_meta = self._client_meta_snapshot(client)
                trace_classification = str((llm_meta.get("trace") or {}).get("classification") or "").strip()
                if not content and trace_classification:
                    fallback_reason = trace_classification
            if not content:
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
                "llm_trace": llm_meta.get("trace") or {},
                "llm_metrics": llm_meta.get("metrics") or {},
            }
            if source == "local_agent":
                meta["person_name"] = str(local_result.get("person_name") or "").strip()
            yield self._sse_data({"type": "meta", "meta": meta})
            yield self._sse_data({"type": "done"})

        return 200, _event_iter()
