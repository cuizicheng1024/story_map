import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Tuple


class ProxyService:
    def __init__(
        self,
        *,
        get_llm_client: Callable[..., object],
        local_history_reply: Callable[[object], str],
        logger: object,
        max_workers: int = 2,
        timeout_env_name: str = "STORY_MAP_PROXY_LLM_TIMEOUT",
    ) -> None:
        self._get_llm_client = get_llm_client
        self._local_history_reply = local_history_reply
        self._logger = logger
        self._timeout_env_name = timeout_env_name
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def proxy_llm(self, data: object) -> Tuple[int, Dict[str, object]]:
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "body required"}
        messages = data.get("messages", [])
        temperature = data.get("temperature", 0.1)

        content = ""
        used_fallback = False
        try:
            client = self._get_llm_client()
            future = self._executor.submit(client.think, messages, temperature=temperature)
            timeout_s = int(os.getenv(self._timeout_env_name, "25") or "25")
            content = future.result(timeout=timeout_s)
        except Exception as exc:
            self._logger.warning("llm_proxy_primary_failed error=%s", exc)
            content = self._local_history_reply(messages)
            used_fallback = True
        if not content:
            self._logger.warning("llm_proxy_empty_response use_fallback=true")
            content = self._local_history_reply(messages)
            used_fallback = True
        if content:
            content = content.encode("utf-8", "replace").decode("utf-8", "replace")
        return 200, {
            "choices": [{"message": {"content": content or ""}}],
            "meta": {"used_fallback": used_fallback},
        }
