"""
职责：负责“故事生成”（调用 LLM），不包含地图或距离相关逻辑。
提示词从 docs/ 目录加载，便于集中管理与调优。
"""
import argparse
import hashlib
import json
import os
import threading
import time
import uuid
import requests
from typing import Dict, List, Optional, Tuple
from typing import Iterator

from ..core.env_utils import load_project_env
from ..core.project_paths import classify_story_person_authenticity, project_root_path
from ..runtime.legacy_agent import graph as story_agent_graph_utils
from ..runtime.legacy_agent import runtime as story_agent_runtime_utils

def _project_root() -> str:
    return str(project_root_path())


load_project_env(from_file=__file__, override=False)

_MAX_TEXT_LEN = 200
_NEGATIVE_CACHEABLE_CLASSIFICATIONS = {
    "timeout",
    "ssl",
    "network",
    "dns",
    "connection_reset",
    "rate_limit",
    "http_5xx",
}


class LLMRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        classification: str,
        request_id: str,
        provider: str,
        endpoint: str,
        status_code: Optional[int] = None,
        duration_ms: int = 0,
        retryable: bool = True,
        response_excerpt: str = "",
    ):
        super().__init__(message)
        self.classification = classification
        self.request_id = request_id
        self.provider = provider
        self.endpoint = endpoint
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.retryable = retryable
        self.response_excerpt = response_excerpt


def _safe_excerpt(text: object, limit: int = 240) -> str:
    content = str(text or "").strip()
    if len(content) <= limit:
        return content
    return f"{content[: limit - 3]}..."


def _message_stats(messages: List[Dict[str, str]]) -> Dict[str, int]:
    total_chars = 0
    total_messages = 0
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        total_messages += 1
        total_chars += len(str(item.get("content") or ""))
    return {"message_count": total_messages, "char_count": total_chars}


def _classify_request_exception(exc: Exception) -> str:
    message = str(exc or "").lower()
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl"
    if isinstance(exc, requests.ConnectionError):
        if "connection reset" in message or "reset by peer" in message:
            return "connection_reset"
        if "name resolution" in message or "temporary failure in name resolution" in message:
            return "dns"
        return "network"
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status in {401, 403}:
            return "auth"
        if status == 429:
            return "rate_limit"
        if isinstance(status, int):
            if 400 <= status < 500:
                return "http_4xx"
            if status >= 500:
                return "http_5xx"
    return "unknown"


def _validate_person(text: object) -> Optional[str]:
    if not isinstance(text, str):
        return "输入必须是字符串"
    cleaned = text.strip()
    if not cleaned:
        return "输入不能为空"
    if len(cleaned) > _MAX_TEXT_LEN:
        return f"输入过长（最多 {_MAX_TEXT_LEN} 字符）"
    return None


class StoryAgentLLM:
    """
    主要职责：
    - 统一管理模型 ID、API Key、Base URL 等基础配置
    - 调用 MiniMax 兼容接口来执行大模型对话
    - 兼容 OpenAI / Anthropic 风格的 messages 输入
    """
    def __init__(
        self,
        model: Optional[str] = None,
        apiKey: Optional[str] = None,
        baseUrl: Optional[str] = None,
        timeout: Optional[int] = None,
        event_callback: Optional[callable] = None,
        timeout_resolver: Optional[callable] = None,
    ):
        """
        初始化客户端。
        优先使用传入的参数；如果某个参数为 None，则会回退到环境变量：
        - LLM_MODEL_ID  -> 大模型 ID
        - LLM_API_KEY   -> OpenAI 兼容接口 API Key
        - LLM_BASE_URL  -> OpenAI 兼容接口 Base URL
        """
        fallback_model = (
            os.getenv("LLM_MODEL_ID")
            or os.getenv("MINIMAX_MODEL")
            or os.getenv("MINIMAX_MODEL_ID")
            or os.getenv("minimax_MODEL")
            or os.getenv("minimax_MODEL_ID")
            or os.getenv("MODEL")
            or os.getenv("MIMO_MODEL")
            or os.getenv("MIMO_MODEL_ID")
        )
        fallback_key = (
            os.getenv("MINIMAX_API_KEY")
            or os.getenv("MINIMAX_API_Key")
            or os.getenv("minimax_API_KEY")
            or os.getenv("minimax_API_Key")
            or os.getenv("MIMO_API_KEY")
            or os.getenv("MIMO_API_Key")
            or os.getenv("MIMO_APIKEY")
            or os.getenv("MIMO_APIKey")
            or os.getenv("API_KEY")
            or os.getenv("API_Key")
        )
        fallback_base = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("MINIMAX_BASE_URL")
            or os.getenv("minimax_BASE_URL")
            or os.getenv("MINIMAX_API_BASE_URL")
            or os.getenv("minimax_API_Base_URL")
            or os.getenv("MIMO_BASE_URL")
            or os.getenv("BASE_URL")
            or "https://api.minimaxi.com/v1"
        )

        resolved_base = (baseUrl or os.getenv("LLM_BASE_URL") or fallback_base or "").strip()
        base_lower = str(resolved_base or "").strip().lower()
        default_model = "MiniMax-M3" if "minimax" in base_lower else "MiniMax-M3"
        self.model = model or os.getenv("LLM_MODEL_ID") or fallback_model or default_model
        self.event_callback = event_callback
        self.timeout_resolver = timeout_resolver
        self.apiKey = apiKey or os.getenv("LLM_API_KEY") or fallback_key
        self.baseUrl = resolved_base or fallback_base
        # Increase default timeout to 300 seconds (5 minutes)
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "300"))
        provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        if provider == "mimo":
            provider = "minimax"
        if provider != "minimax":
            provider = "minimax"
        self.provider = provider
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", os.getenv("MINIMAX_MAX_TOKENS", "4096")) or "4096")
        self._uses_anthropic_api = self._detect_anthropic_api(self.baseUrl)
        insecure_ssl = (os.getenv("STORY_AGENT_ALLOW_INSECURE_SSL") or os.getenv("LLM_ALLOW_INSECURE_SSL") or "").strip().lower()
        self.verify_ssl = insecure_ssl not in {"1", "true", "yes", "on"}
        self.max_trace_entries = int(os.getenv("LLM_TRACE_MAX_ENTRIES", "50") or "50")
        self.request_traces: List[Dict[str, object]] = []
        self.last_request_trace: Dict[str, object] = {}
        self.last_agent_runtime: Dict[str, object] = {}
        self.connect_timeout = max(1, int(os.getenv("LLM_CONNECT_TIMEOUT", str(self.timeout)) or str(self.timeout)))
        self.read_timeout = max(1, int(os.getenv("LLM_READ_TIMEOUT", str(self.timeout)) or str(self.timeout)))
        self.stream_read_timeout = max(1, int(os.getenv("LLM_STREAM_READ_TIMEOUT", str(self.read_timeout)) or str(self.read_timeout)))
        self.negative_cache_ttl = max(1, int(os.getenv("LLM_FAILURE_NEGATIVE_CACHE_TTL", "30") or "30"))
        self._failure_negative_cache: Dict[str, Dict[str, object]] = {}
        self._negative_cache_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        self._metrics: Dict[str, int] = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "timeouts": 0,
            "negative_cache_hits": 0,
            "stream_requests": 0,
            "stream_successes": 0,
            "stream_failures": 0,
        }

        if not self.model or not self.apiKey or not self.baseUrl:
            raise ValueError("模型ID、API密钥和服务地址必须被提供或在.env文件中定义。")

    def _emit(self, message: str) -> None:
        if not self.event_callback:
            return
        try:
            self.event_callback(message)
        except Exception:
            pass

    def _store_trace(self, trace: Dict[str, object]) -> None:
        with self._trace_lock:
            self.last_request_trace = dict(trace)
            self.request_traces.append(dict(trace))
            if len(self.request_traces) > self.max_trace_entries:
                self.request_traces = self.request_traces[-self.max_trace_entries :]

    def latest_trace(self) -> Dict[str, object]:
        with self._trace_lock:
            return dict(self.last_request_trace)

    def health_snapshot(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "timeout": self.timeout,
            "timeout_config": {
                "total": self.timeout,
                "connect": self.connect_timeout,
                "read": self.read_timeout,
                "stream_read": self.stream_read_timeout,
            },
            "negative_cache_ttl": self.negative_cache_ttl,
            "metrics": self.metrics_snapshot(),
            "uses_anthropic_api": self._uses_anthropic_api,
            "verify_ssl": self.verify_ssl,
            "last_request_trace": self.latest_trace(),
        }

    def metrics_snapshot(self) -> Dict[str, object]:
        with self._metrics_lock:
            metrics = {k: int(v) for k, v in self._metrics.items()}
        requests_total = max(1, metrics.get("requests", 0))
        stream_total = max(1, metrics.get("stream_requests", 0))
        return {
            **metrics,
            "success_rate": round(metrics.get("successes", 0) / requests_total, 4),
            "timeout_rate": round(metrics.get("timeouts", 0) / requests_total, 4),
            "negative_cache_hit_rate": round(metrics.get("negative_cache_hits", 0) / requests_total, 4),
            "stream_success_rate": round(metrics.get("stream_successes", 0) / stream_total, 4),
            "negative_cache_size": self._negative_cache_size(),
        }

    def _record_metric(self, key: str, amount: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[key] = int(self._metrics.get(key, 0)) + int(amount)

    def _negative_cache_size(self) -> int:
        now = time.time()
        with self._negative_cache_lock:
            expired = [key for key, value in self._failure_negative_cache.items() if float(value.get("expires_at") or 0) <= now]
            for key in expired:
                self._failure_negative_cache.pop(key, None)
            return len(self._failure_negative_cache)

    def _request_signature(self, messages: List[Dict[str, str]], temperature: float, *, stream: bool) -> str:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "temperature": float(temperature),
            "stream": bool(stream),
            "messages": messages,
        }
        return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _negative_cache_get(self, key: str) -> Optional[Dict[str, object]]:
        cache_key = str(key or "").strip()
        if not cache_key:
            return None
        now = time.time()
        with self._negative_cache_lock:
            item = self._failure_negative_cache.get(cache_key)
            if not isinstance(item, dict):
                return None
            if float(item.get("expires_at") or 0) <= now:
                self._failure_negative_cache.pop(cache_key, None)
                return None
            return dict(item)

    def _negative_cache_set(self, key: str, *, classification: str, error: str) -> None:
        cache_key = str(key or "").strip()
        if not cache_key:
            return
        with self._negative_cache_lock:
            self._failure_negative_cache[cache_key] = {
                "classification": str(classification or "unknown"),
                "error": str(error or "").strip(),
                "expires_at": time.time() + self.negative_cache_ttl,
            }

    def _negative_cache_clear(self, key: str) -> None:
        cache_key = str(key or "").strip()
        if not cache_key:
            return
        with self._negative_cache_lock:
            self._failure_negative_cache.pop(cache_key, None)

    def _timeout_value(self, *, stream: bool = False, timeout_seconds: Optional[int] = None) -> Tuple[int, int]:
        if timeout_seconds is not None:
            adjusted = max(1, int(timeout_seconds))
            return (adjusted, adjusted)
        return (self.connect_timeout, self.stream_read_timeout if stream else self.read_timeout)

    def _build_negative_cache_trace(
        self,
        *,
        request_id: str,
        key: str,
        cached: Dict[str, object],
        base_trace: Dict[str, object],
        stream: bool,
    ) -> Dict[str, object]:
        expires_at = float(cached.get("expires_at") or 0)
        return {
            **base_trace,
            "request_id": request_id,
            "success": False,
            "classification": str(cached.get("classification") or "negative_cache"),
            "error": str(cached.get("error") or "negative cache hit").strip(),
            "retryable": False,
            "negative_cache_key": key,
            "negative_cache_expires_in_ms": max(0, int((expires_at - time.time()) * 1000)),
            "stream": bool(stream),
        }

    def _post_json(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, object],
        request_id: str,
        verify: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[requests.Response, Dict[str, object]]:
        request_headers = dict(headers or {})
        request_headers.setdefault("X-Request-Id", request_id)
        started = time.perf_counter()
        resolved_verify = self.verify_ssl if verify is None else bool(verify)
        try:
            resp = requests.post(
                url,
                headers=request_headers,
                json=payload,
                timeout=self._timeout_value(stream=False, timeout_seconds=timeout_seconds),
                verify=resolved_verify,
            )
        except requests.RequestException as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            classification = _classify_request_exception(exc)
            raise LLMRequestError(
                str(exc),
                classification=classification,
                request_id=request_id,
                provider=self.provider,
                endpoint=url,
                duration_ms=duration_ms,
                retryable=classification not in {"auth", "http_4xx"},
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        meta = {
            "status_code": resp.status_code,
            "duration_ms": duration_ms,
            "verify_ssl": resolved_verify,
            "response_request_id": resp.headers.get("x-request-id")
            or resp.headers.get("request-id")
            or resp.headers.get("trace-id")
            or "",
        }
        return resp, meta

    def _raise_http_error(
        self,
        *,
        response: requests.Response,
        request_id: str,
        duration_ms: int,
    ) -> None:
        classification = "http_4xx"
        status_code = int(response.status_code)
        if status_code in {401, 403}:
            classification = "auth"
        elif status_code == 429:
            classification = "rate_limit"
        elif status_code >= 500:
            classification = "http_5xx"
        raise LLMRequestError(
            f"HTTP {status_code}: {_safe_excerpt(response.text)}",
            classification=classification,
            request_id=request_id,
            provider=self.provider,
            endpoint=str(response.request.url if response.request else ""),
            status_code=status_code,
            duration_ms=duration_ms,
            retryable=classification not in {"auth", "http_4xx"},
            response_excerpt=_safe_excerpt(response.text),
        )

    def think(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        *,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> Optional[str]:
        silent = (os.getenv("STORY_AGENT_SILENT") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
        effective_retries = max(1, int(max_retries or 3))
        effective_timeout = max(1, int(timeout or self.timeout))
        if callable(self.timeout_resolver):
            try:
                remaining_budget = int(self.timeout_resolver() or 0)
            except Exception:
                remaining_budget = 0
            if remaining_budget > 0:
                effective_timeout = max(1, min(effective_timeout, remaining_budget))
        provider = "minimax"
        request_signature = self._request_signature(messages, temperature, stream=False)

        self._emit(f"🧠 正在调用 {self.model} 模型 (via {provider})...")
        request_id = uuid.uuid4().hex[:12]
        base_trace: Dict[str, object] = {
            "request_id": request_id,
            "provider": provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "temperature": float(temperature),
            "message_stats": _message_stats(messages),
            "max_retries": effective_retries,
            "timeout": effective_timeout,
        }
        self._record_metric("requests")
        negative_cached = self._negative_cache_get(request_signature)
        if negative_cached:
            self._record_metric("negative_cache_hits")
            trace = self._build_negative_cache_trace(
                request_id=request_id,
                key=request_signature,
                cached=negative_cached,
                base_trace=base_trace,
                stream=False,
            )
            self._store_trace(trace)
            return None

        for attempt in range(1, effective_retries + 1):
            started = time.perf_counter()
            try:
                content, meta = self._think_minimax(
                    messages,
                    temperature=temperature,
                    request_id=request_id,
                    timeout_seconds=effective_timeout,
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                trace = {
                    **base_trace,
                    **meta,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                    "success": True,
                    "classification": "ok",
                    "response_chars": len(str(content or "")),
                }
                self._store_trace(trace)
                self._negative_cache_clear(request_signature)
                self._record_metric("successes")

                if content:
                    self._emit("✅ 大语言模型响应成功")
                    return content
                else:
                    if not silent:
                        print("⚠️ 模型返回内容为空")
                    # 空内容不视为错误，直接返回空字符串
                    return ""

            except Exception as e:
                duration_ms = int((time.perf_counter() - started) * 1000)
                status_code = getattr(e, "status_code", None)
                classification = getattr(e, "classification", "") or _classify_request_exception(e)
                retryable = getattr(e, "retryable", True)
                if classification == "timeout":
                    self._record_metric("timeouts")
                trace = {
                    **base_trace,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                    "success": False,
                    "classification": classification,
                    "status_code": status_code,
                    "endpoint": getattr(e, "endpoint", ""),
                    "error": str(e),
                    "retryable": retryable,
                    "response_excerpt": getattr(e, "response_excerpt", ""),
                }
                self._store_trace(trace)
                if attempt >= effective_retries or not retryable:
                    self._record_metric("failures")
                    if classification in _NEGATIVE_CACHEABLE_CLASSIFICATIONS:
                        self._negative_cache_set(request_signature, classification=classification, error=str(e))
                if not silent:
                    print(f"⚠️ 第 {attempt}/{effective_retries} 次尝试失败 [{classification}]: {e}")
                if attempt < effective_retries and retryable:
                    wait_time = 2 * attempt  # 简单的指数退避
                    if not silent:
                        print(f"⏳ {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    if not silent:
                        print(f"❌ 调用LLM API最终失败 [{classification}] request_id={request_id}: {e}")
                    self._emit(f"❌ 调用LLM API最终失败 [{classification}] request_id={request_id}: {e}")
                    return None

    def stream_think(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
    ) -> Iterator[str]:
        request_id = str(request_id or uuid.uuid4().hex)
        request_signature = self._request_signature(messages, temperature, stream=True)
        base_trace: Dict[str, object] = {
            "request_id": request_id,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "temperature": float(temperature),
            "message_stats": _message_stats(messages),
            "timeout": self.timeout,
            "stream": True,
        }
        if self.provider != "minimax":
            content = self.think(messages, temperature=temperature) or ""
            if content:
                yield content
            return
        if self._uses_anthropic_api:
            content = self.think(messages, temperature=temperature) or ""
            if content:
                for chunk in self._chunk_text(content):
                    yield chunk
            return
        self._record_metric("requests")
        self._record_metric("stream_requests")
        negative_cached = self._negative_cache_get(request_signature)
        if negative_cached:
            self._record_metric("negative_cache_hits")
            trace = self._build_negative_cache_trace(
                request_id=request_id,
                key=request_signature,
                cached=negative_cached,
                base_trace=base_trace,
                stream=True,
            )
            self._store_trace(trace)
            raise LLMRequestError(
                str(trace.get("error") or "negative cache hit"),
                classification=str(trace.get("classification") or "negative_cache"),
                request_id=request_id,
                provider=self.provider,
                endpoint="",
                duration_ms=0,
                retryable=False,
            )
        yield from self._stream_minimax_openai(
            messages,
            temperature=temperature,
            request_id=request_id,
            request_signature=request_signature,
            base_trace=base_trace,
        )

    def check_health(
        self,
        *,
        prompt: str = "请只回复 OK",
        attempts: int = 1,
        temperature: float = 0,
    ) -> Dict[str, object]:
        results: List[Dict[str, object]] = []
        for _ in range(max(1, int(attempts))):
            content = self.think([{"role": "user", "content": prompt}], temperature=temperature)
            trace = self.latest_trace()
            results.append(
                {
                    "ok": bool(content),
                    "content_excerpt": _safe_excerpt(content),
                    "trace": trace,
                }
            )
        success_count = sum(1 for item in results if item["ok"])
        return {
            "ok": success_count == len(results),
            "attempts": len(results),
            "success_count": success_count,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "results": results,
        }

    @staticmethod
    def _detect_anthropic_api(base_url: str) -> bool:
        base = str(base_url or "").strip().lower()
        if "/anthropic" in base:
            return True
        return False

    @staticmethod
    def _openai_endpoint(base_url: str) -> str:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            base = "https://api.minimaxi.com/v1"
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @staticmethod
    def _anthropic_endpoint(base_url: str) -> str:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            base = "https://api.minimaxi.com/anthropic"
        if base.endswith("/v1/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    @staticmethod
    def _normalize_anthropic_messages(messages: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]]]:
        system_parts: List[str] = []
        normalized: List[Dict[str, str]] = []
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = item.get("content") or ""
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(str(block.get("text") or ""))
                content = "\n".join(t for t in texts if t)
            content_str = str(content or "").strip()
            if not content_str:
                continue
            if role == "system":
                system_parts.append(content_str)
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            if normalized and normalized[-1].get("role") == role:
                prev = str(normalized[-1].get("content") or "").strip()
                normalized[-1]["content"] = f"{prev}\n\n{content_str}" if prev else content_str
            else:
                normalized.append({"role": role, "content": content_str})
        if not normalized:
            normalized = [{"role": "user", "content": "请继续。"}]
        return "\n\n".join(system_parts).strip(), normalized

    def _think_minimax(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[str, Dict[str, object]]:
        if self._uses_anthropic_api:
            return self._think_minimax_anthropic(
                messages,
                temperature=temperature,
                request_id=request_id,
                timeout_seconds=timeout_seconds,
            )
        return self._think_minimax_openai(
            messages,
            temperature=temperature,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        )

    def _think_minimax_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[str, Dict[str, object]]:
        url = self._openai_endpoint(self.baseUrl)
        headers = {
            "Content-Type": "application/json",
        }
        if self.apiKey:
            headers["api-key"] = self.apiKey
            headers["x-api-key"] = self.apiKey
            headers["Authorization"] = f"Bearer {self.apiKey}"
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        resp, meta = self._post_json(
            url=url,
            headers=headers,
            payload=payload,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        )
        if not resp.ok:
            self._raise_http_error(response=resp, request_id=request_id, duration_ms=int(meta.get("duration_ms") or 0))
        data = resp.json()
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                return message.get("content") or "", {"endpoint": url, **meta}
        if isinstance(data, dict) and isinstance(data.get("content"), str):
            return data.get("content") or "", {"endpoint": url, **meta}
        return "", {"endpoint": url, **meta}

    @staticmethod
    def _chunk_text(text: str, *, chunk_size: int = 24) -> Iterator[str]:
        content = str(text or "")
        if not content:
            return
        for idx in range(0, len(content), max(1, int(chunk_size))):
            yield content[idx : idx + max(1, int(chunk_size))]

    @staticmethod
    def _stream_choice_text(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                parts.append(str(item.get("text") or ""))
                        return "".join(parts)
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
        if isinstance(payload.get("content"), str):
            return str(payload.get("content") or "")
        return ""

    def _stream_minimax_openai(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0,
        request_id: str = "",
        request_signature: str = "",
        base_trace: Optional[Dict[str, object]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Iterator[str]:
        url = self._openai_endpoint(self.baseUrl)
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.apiKey:
            headers["api-key"] = self.apiKey
            headers["x-api-key"] = self.apiKey
            headers["Authorization"] = f"Bearer {self.apiKey}"
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        request_headers = dict(headers)
        request_headers.setdefault("X-Request-Id", request_id)
        started = time.perf_counter()
        accumulated = ""
        try:
            with requests.post(
                url,
                headers=request_headers,
                json=payload,
                timeout=self._timeout_value(stream=True, timeout_seconds=timeout_seconds),
                verify=self.verify_ssl,
                stream=True,
            ) as resp:
                duration_ms = int((time.perf_counter() - started) * 1000)
                meta = {
                    "status_code": resp.status_code,
                    "duration_ms": duration_ms,
                    "verify_ssl": self.verify_ssl,
                    "response_request_id": resp.headers.get("x-request-id")
                    or resp.headers.get("request-id")
                    or resp.headers.get("trace-id")
                    or "",
                    "endpoint": url,
                    "stream": True,
                }
                if not resp.ok:
                    self._raise_http_error(response=resp, request_id=request_id, duration_ms=duration_ms)
                # requests.iter_lines() defaults to a relatively large chunk size,
                # which can visually collapse upstream SSE into a near one-shot reply.
                for raw_line in resp.iter_lines(chunk_size=1, decode_unicode=True):
                    line = str(raw_line or "").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if not body:
                        continue
                    if body == "[DONE]":
                        break
                    try:
                        data = json.loads(body)
                    except Exception:
                        continue
                    piece = self._stream_choice_text(data)
                    if not piece:
                        continue
                    accumulated += piece
                    yield piece
                self._store_trace(
                    {
                        **(base_trace or {}),
                        "endpoint": url,
                        "status_code": resp.status_code,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "request_id": request_id,
                        "response_request_id": meta.get("response_request_id") or "",
                        "stream": True,
                        "success": True,
                        "classification": "ok",
                        "content_excerpt": _safe_excerpt(accumulated),
                    }
                )
                self._negative_cache_clear(request_signature)
                self._record_metric("successes")
                self._record_metric("stream_successes")
        except requests.RequestException as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            classification = _classify_request_exception(exc)
            if classification == "timeout":
                self._record_metric("timeouts")
            self._record_metric("failures")
            self._record_metric("stream_failures")
            if classification in _NEGATIVE_CACHEABLE_CLASSIFICATIONS:
                self._negative_cache_set(request_signature, classification=classification, error=str(exc))
            self._store_trace(
                {
                    **(base_trace or {}),
                    "endpoint": url,
                    "request_id": request_id,
                    "duration_ms": duration_ms,
                    "success": False,
                    "classification": classification,
                    "retryable": classification not in {"auth", "http_4xx"},
                    "error": str(exc),
                    "stream": True,
                }
            )
            raise LLMRequestError(
                str(exc),
                classification=classification,
                request_id=request_id,
                provider=self.provider,
                endpoint=url,
                duration_ms=duration_ms,
                retryable=classification not in {"auth", "http_4xx"},
            ) from exc

    def _think_minimax_anthropic(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[str, Dict[str, object]]:
        url = self._anthropic_endpoint(self.baseUrl)
        system_prompt, normalized_messages = self._normalize_anthropic_messages(messages)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.apiKey,
            "anthropic-version": os.getenv("MINIMAX_ANTHROPIC_VERSION", "2023-06-01"),
        }
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": normalized_messages,
            "max_tokens": self.max_tokens,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if temperature is not None:
            payload["temperature"] = temperature
        resp, meta = self._post_json(
            url=url,
            headers=headers,
            payload=payload,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        )
        if not resp.ok:
            self._raise_http_error(response=resp, request_id=request_id, duration_ms=int(meta.get("duration_ms") or 0))
        data = resp.json()
        blocks = data.get("content", []) if isinstance(data, dict) else []
        texts: List[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                if text:
                    texts.append(text)
        if texts:
            return "\n".join(texts).strip(), {"endpoint": url, **meta}
        if isinstance(data, dict) and isinstance(data.get("output_text"), str):
            return data.get("output_text") or "", {"endpoint": url, **meta}
        return "", {"endpoint": url, **meta}


def _read_prompt(relpath: str) -> str:
    """
    读取 docs/ 目录下的提示词文件内容。
    """
    rel = str(relpath or "").strip()
    if not rel:
        raise FileNotFoundError("prompt path is empty")
    root = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(_project_root(), "storymap", "docs", rel),
        os.path.join(root, "..", "..", "docs", rel),
        os.path.join(root, "..", "docs", rel),
    ]
    for prompt_path in candidates:
        normalized = os.path.abspath(prompt_path)
        if os.path.exists(normalized):
            with open(normalized, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(candidates[0])


def _legacy_generate_historical_markdown(llm: "StoryAgentLLM", person: str) -> Optional[str]:
    """
    生成指定人物的生平 Markdown。
    """
    system_prompt = _read_prompt("story_system_prompt.md")
    user_prompt = f"请整理历史人物「{person}」的生平信息，并按要求输出。"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return llm.think(messages, temperature=0.1)


def generate_historical_markdown(llm: "StoryAgentLLM", person: str) -> Optional[str]:
    """
    使用 Supervisor / Worker / Critic 的多 Agent 工作流生成 Markdown，
    若图工作流不可用或返回空结果，则回退到原有单次生成逻辑。
    """
    accepted, reason = classify_story_person_authenticity(person, allow_unknown=True)
    if llm is not None:
        llm.last_agent_runtime = {}
    if not accepted:
        error = f"人物真实性过滤拦截：{person} ({reason or 'non_authentic'})"
        if llm and hasattr(llm, "_emit"):
            llm._emit(f"⛔ {error}")
        if llm is not None:
            llm.last_agent_runtime = story_agent_runtime_utils.build_runtime_snapshot(
                person,
                {
                    "state": {
                        "degraded_reasons": [f"authenticity_filter:{reason or 'non_authentic'}"],
                        "execution_trace": ["finish_agent"],
                    }
                },
                fallback="authenticity_filter",
                error=error,
            )
        return None
    try:
        result = story_agent_graph_utils.generate_markdown_with_agents(llm, person)
        if llm is not None:
            # Persist the full normalized runtime state so PDCA/6M/debug views keep
            # access to validation, feedback, and intermediate artifacts.
            llm.last_agent_runtime = story_agent_runtime_utils.build_runtime_snapshot(person, result)
        markdown = str(result.get("markdown") or "").strip()
        if markdown:
            return markdown
    except Exception as exc:
        if llm and hasattr(llm, "_emit"):
            llm._emit(f"⚠️ 多 Agent 工作流失败，回退单次生成：{exc}")
        if llm is not None:
            llm.last_agent_runtime = story_agent_runtime_utils.build_runtime_snapshot(
                person,
                fallback="legacy_generate_historical_markdown",
                error=str(exc).strip() or exc.__class__.__name__,
            )
    markdown = _legacy_generate_historical_markdown(llm, person)
    if llm is not None:
        llm.last_agent_runtime = story_agent_runtime_utils.mark_runtime_legacy_fallback(
            getattr(llm, "last_agent_runtime", {}),
            person=person,
            markdown=markdown,
        )
    return markdown


def extract_historical_figures(llm: "StoryAgentLLM", text: object) -> List[str]:
    """
    从输入文本中抽取历史人物名称列表。
    """
    if not isinstance(text, str):
        return []
    sys_prompt = _read_prompt("extract_names_prompt.md")
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": text},
    ]
    raw = llm.think(messages, temperature=0)
    if not raw:
        return []
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            names = [str(x).strip() for x in data if str(x).strip()]
            return list(dict.fromkeys(names))
    except Exception as e:
        print(f"⚠️ 解析人物列表失败 (JSON解析异常): {e}. 尝试将原文视为单个人名。")
        if llm and hasattr(llm, "_emit"):
            llm._emit(f"⚠️ 解析人物列表失败: {e}")
    cleaned = raw.strip()
    return [cleaned] if cleaned else []


def save_markdown(person: str, content: str) -> str:
    """
    保存 Markdown 到 examples/story/ 目录，若存在则覆盖。
    """
    root = _project_root()
    base = os.path.join(root, "storymap", "examples", "story")
    os.makedirs(base, exist_ok=True)
    safe_person = str(person or "").translate(str.maketrans({c: "_" for c in '\\/:*?"<>|'})).strip() or "map"
    filename = f"{safe_person}.md"
    path = os.path.join(base, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 人物生平已保存: {path}")
    return path


def run_interactive(llm: "StoryAgentLLM") -> None:
    """
    交互式输入人物并生成 Markdown。
    """
    while True:
        try:
            name = input("请输入历史人物（q/quit/exit 退出）：").strip()
        except EOFError:
            break
        if not name:
            continue
        err = _validate_person(name)
        if err:
            print(err)
            continue
        if name.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        targets = extract_historical_figures(llm, name)
        if not targets:
            print("未识别到历史人物，请重试。")
            continue
        for person in targets:
            md = generate_historical_markdown(llm, person)
            if md:
                saved = save_markdown(person, md)
                print(f"已生成：{saved}")
                print(md)
            else:
                print(f"未取得「{person}」结果。")


def main():
    parser = argparse.ArgumentParser(
        description="基于环境变量配置的 LLM，生成历史人物的 Markdown 生平信息。"
    )
    parser.add_argument(
        "-p", "--person", help="历史人物姓名，例如：李白、杜甫、诸葛亮", required=False
    )
    args = parser.parse_args()

    if args.person:
        try:
            err = _validate_person(args.person)
            if err:
                print(err)
                return
            client = StoryAgentLLM()
            targets = extract_historical_figures(client, args.person)
            if not targets:
                print("未识别到历史人物。")
                return
            for person in targets:
                md = generate_historical_markdown(client, person)
                if md:
                    saved = save_markdown(person, md)
                    print(f"已生成：{saved}")
                    print(md)
        except ValueError as e:
            print(e)
        return

    try:
        client = StoryAgentLLM()
        run_interactive(client)
    except ValueError as e:
        print(e)


if __name__ == "__main__":
    main()
