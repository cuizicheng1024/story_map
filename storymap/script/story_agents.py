"""
职责：负责“故事生成”（调用 LLM），不包含地图或距离相关逻辑。
提示词从 docs/ 目录加载，便于集中管理与调优。
"""
import argparse
import json
import os
import time
import uuid
import requests
from typing import Dict, List, Optional, Tuple

try:
    from .env_utils import load_project_env
    from . import story_agent_runtime as story_agent_runtime_utils
    from . import story_agent_graph as story_agent_graph_utils
except ImportError:
    from env_utils import load_project_env
    import story_agent_runtime as story_agent_runtime_utils
    import story_agent_graph as story_agent_graph_utils

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


load_project_env(from_file=__file__, override=False)

_MAX_TEXT_LEN = 200


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
    if isinstance(exc, requests.SSLError):
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
    - 调用 Qveris 的 Execute Tool 接口来执行大模型对话
    - 兼容 OpenAI 格式的 messages 输入
    """
    def __init__(
        self,
        model: Optional[str] = None,
        apiKey: Optional[str] = None,
        baseUrl: Optional[str] = None,
        timeout: Optional[int] = None,
        event_callback: Optional[callable] = None,
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
            or "https://api.minimaxi.com/anthropic"
        )

        resolved_base = (baseUrl or os.getenv("LLM_BASE_URL") or fallback_base or "").strip()
        base_lower = str(resolved_base or "").strip().lower()
        default_model = "MiniMax-M3" if "minimax" in base_lower else "MiniMax-M3"
        self.model = model or os.getenv("LLM_MODEL_ID") or fallback_model or default_model
        self.event_callback = event_callback
        self.apiKey = apiKey or os.getenv("LLM_API_KEY") or fallback_key
        self.baseUrl = resolved_base or fallback_base
        # Increase default timeout to 300 seconds (5 minutes)
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "300"))
        provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        if not provider:
            provider = "minimax" if "minimax" in str(self.baseUrl or "").lower() else "qveris"
        if provider == "mimo":
            provider = "minimax"
        self.provider = provider
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", os.getenv("MINIMAX_MAX_TOKENS", "4096")) or "4096")
        self._uses_anthropic_api = self._detect_anthropic_api(self.baseUrl, self.provider)
        insecure_ssl = (os.getenv("STORY_AGENT_ALLOW_INSECURE_SSL") or os.getenv("LLM_ALLOW_INSECURE_SSL") or "").strip().lower()
        self.verify_ssl = insecure_ssl not in {"1", "true", "yes", "on"}
        self.max_trace_entries = int(os.getenv("LLM_TRACE_MAX_ENTRIES", "50") or "50")
        self.request_traces: List[Dict[str, object]] = []
        self.last_request_trace: Dict[str, object] = {}
        self.last_agent_runtime: Dict[str, object] = {}

        self.tool_id = "bigmodel.chat.completions.create.v4.bbf1f5ab"

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
        self.last_request_trace = dict(trace)
        self.request_traces.append(dict(trace))
        if len(self.request_traces) > self.max_trace_entries:
            self.request_traces = self.request_traces[-self.max_trace_entries :]

    def latest_trace(self) -> Dict[str, object]:
        return dict(self.last_request_trace)

    def health_snapshot(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "timeout": self.timeout,
            "uses_anthropic_api": self._uses_anthropic_api,
            "verify_ssl": self.verify_ssl,
            "last_request_trace": self.latest_trace(),
        }

    def _post_json(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, object],
        request_id: str,
        verify: Optional[bool] = None,
    ) -> Tuple[requests.Response, Dict[str, object]]:
        request_headers = dict(headers or {})
        request_headers.setdefault("X-Request-Id", request_id)
        started = time.perf_counter()
        resolved_verify = self.verify_ssl if verify is None else bool(verify)
        try:
            resp = requests.post(url, headers=request_headers, json=payload, timeout=self.timeout, verify=resolved_verify)
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

    def think(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
        silent = (os.getenv("STORY_AGENT_SILENT") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
        max_retries = 3
        provider = (self.provider or "qveris").strip().lower()
        if provider == "mimo":
            provider = "minimax"
        if provider not in {"qveris", "minimax"}:
            provider = "qveris"

        if not silent:
            print(f"🧠 正在调用 {self.model} 模型 (via {provider})...")
        self._emit(f"🧠 正在调用 {self.model} 模型 (via {provider})...")
        request_id = uuid.uuid4().hex[:12]
        base_trace: Dict[str, object] = {
            "request_id": request_id,
            "provider": provider,
            "model": self.model,
            "base_url": self.baseUrl,
            "temperature": float(temperature),
            "message_stats": _message_stats(messages),
            "max_retries": max_retries,
        }

        for attempt in range(1, max_retries + 1):
            started = time.perf_counter()
            try:
                if provider == "minimax":
                    content, meta = self._think_minimax(messages, temperature=temperature, request_id=request_id)
                else:
                    content, meta = self._think_qveris(messages, temperature=temperature, request_id=request_id)
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

                if content:
                    if not silent:
                        print(content)
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
                if not silent:
                    print(f"⚠️ 第 {attempt}/{max_retries} 次尝试失败 [{classification}]: {e}")
                if attempt < max_retries and retryable:
                    wait_time = 2 * attempt  # 简单的指数退避
                    if not silent:
                        print(f"⏳ {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    if not silent:
                        print(f"❌ 调用LLM API最终失败 [{classification}] request_id={request_id}: {e}")
                    self._emit(f"❌ 调用LLM API最终失败 [{classification}] request_id={request_id}: {e}")
                    return None

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
    def _detect_anthropic_api(base_url: str, provider: str) -> bool:
        base = str(base_url or "").strip().lower()
        provider_name = str(provider or "").strip().lower()
        if "/anthropic" in base:
            return True
        if "api.minimaxi.com" in base and provider_name == "minimax":
            return True
        return False

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
    ) -> Tuple[str, Dict[str, object]]:
        if self._uses_anthropic_api:
            return self._think_minimax_anthropic(messages, temperature=temperature, request_id=request_id)
        return self._think_minimax_openai(messages, temperature=temperature, request_id=request_id)

    def _think_minimax_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
    ) -> Tuple[str, Dict[str, object]]:
        url = f"{self.baseUrl.rstrip('/')}/chat/completions"
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
        resp, meta = self._post_json(url=url, headers=headers, payload=payload, request_id=request_id)
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

    def _think_minimax_anthropic(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
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
        resp, meta = self._post_json(url=url, headers=headers, payload=payload, request_id=request_id)
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

    def _think_qveris(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        request_id: str = "",
    ) -> Tuple[str, Dict[str, object]]:
        url = f"{self.baseUrl.rstrip('/')}/tools/execute"
        headers = {"Authorization": f"Bearer {self.apiKey}", "Content-Type": "application/json"}
        params_to_tool = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.apiKey}",
        }
        payload = {"tool_id": self.tool_id, "parameters": params_to_tool}
        resp, meta = self._post_json(url=url, headers=headers, payload=payload, request_id=request_id)
        if not resp.ok:
            self._raise_http_error(response=resp, request_id=request_id, duration_ms=int(meta.get("duration_ms") or 0))
        data = resp.json()
        if not data.get("success"):
            error_msg = data.get("error_message") or "Unknown error"
            raise LLMRequestError(
                f"Qveris execution failed: {error_msg}",
                classification="upstream_error",
                request_id=request_id,
                provider=self.provider,
                endpoint=url,
                status_code=resp.status_code,
                duration_ms=int(meta.get("duration_ms") or 0),
                retryable=True,
                response_excerpt=_safe_excerpt(error_msg),
            )
        tool_result = data.get("result", {}).get("data", {})
        content = ""
        if isinstance(tool_result, dict):
            choices = tool_result.get("choices", [])
            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content", "")
        if not content and isinstance(tool_result, str):
            content = tool_result
        return content, {"endpoint": url, **meta}


def _read_prompt(relpath: str) -> str:
    """
    读取 docs/ 目录下的提示词文件内容。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    # script/../docs -> storymap/docs
    prompt_path = os.path.join(root, "..", "docs", relpath)
    if not os.path.exists(prompt_path):
        root_proj = _project_root()
        prompt_path = os.path.join(root_proj, "storymap", "docs", relpath)

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


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
    if llm is not None:
        llm.last_agent_runtime = {}
    try:
        result = story_agent_graph_utils.generate_markdown_with_agents(llm, person)
        if llm is not None:
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
