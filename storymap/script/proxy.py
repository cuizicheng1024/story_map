import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Dict, Tuple


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

    def proxy_llm(self, data: object) -> Tuple[int, Dict[str, object]]:
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "body required"}
        messages = data.get("messages", [])
        temperature = data.get("temperature", 0.1)

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
            local_content = local_content.encode("utf-8", "replace").decode("utf-8", "replace")
            return 200, {
                "choices": [{"message": {"content": local_content}}],
                "meta": {
                    "used_fallback": False,
                    "source": "local_agent",
                    "person_name": str(local_result.get("person_name") or "").strip(),
                },
            }

        content = ""
        used_fallback = False
        source = "llm"
        future = None
        try:
            client = self._get_llm_client()
            future = self._executor.submit(client.think, messages, temperature=temperature)
            timeout_s = int(os.getenv(self._timeout_env_name, "25") or "25")
            content = future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            if future is not None:
                future.cancel()
            self._reset_executor()
            self._logger.warning("llm_proxy_primary_timeout error=%s", exc)
            content = self._local_history_reply(messages)
            used_fallback = True
            source = "fallback"
        except Exception as exc:
            self._logger.warning("llm_proxy_primary_failed error=%s", exc)
            content = self._local_history_reply(messages)
            used_fallback = True
            source = "fallback"
        if not content:
            self._logger.warning("llm_proxy_empty_response use_fallback=true")
            content = self._local_history_reply(messages)
            used_fallback = True
            source = "fallback"
        if content:
            content = content.encode("utf-8", "replace").decode("utf-8", "replace")
        return 200, {
            "choices": [{"message": {"content": content or ""}}],
            "meta": {"used_fallback": used_fallback, "source": source},
        }
