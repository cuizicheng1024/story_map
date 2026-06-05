"""
职责：负责“故事生成”（调用 LLM），不包含地图或距离相关逻辑。
提示词从 docs/ 目录加载，便于集中管理与调优。
"""
import argparse
import json
import os
import requests
import urllib3
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

# 禁用 urllib3 的不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


local_env = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=local_env)
root = _project_root()
env_candidates = [
    os.path.join(root, ".env"),
    os.path.join(root, "data", ".env"),
    os.path.join(root, "map_story_poster", ".env"),
    os.path.join(root, "external", "map_story_poster", ".env"),
    os.path.abspath(os.path.join(root, "..", ".env")),
    os.path.abspath(os.path.join(root, "..", "..", ".env")),
]
for p in env_candidates:
    try:
        if p and os.path.isfile(p):
            load_dotenv(dotenv_path=p)
    except Exception:
        pass

_MAX_TEXT_LEN = 200


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

    def think(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
        import time
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

        for attempt in range(1, max_retries + 1):
            try:
                if provider == "minimax":
                    content = self._think_minimax(messages, temperature=temperature)
                else:
                    content = self._think_qveris(messages, temperature=temperature)

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
                if not silent:
                    print(f"⚠️ 第 {attempt}/{max_retries} 次尝试失败: {e}")
                if attempt < max_retries:
                    wait_time = 2 * attempt  # 简单的指数退避
                    if not silent:
                        print(f"⏳ {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    if not silent:
                        print(f"❌ 调用LLM API最终失败: {e}")
                    self._emit(f"❌ 调用LLM API最终失败: {e}")

        return None

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

    def _think_minimax(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
        if self._uses_anthropic_api:
            return self._think_minimax_anthropic(messages, temperature=temperature)
        return self._think_minimax_openai(messages, temperature=temperature)

    def _think_minimax_openai(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
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
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                return message.get("content") or ""
        if isinstance(data, dict) and isinstance(data.get("content"), str):
            return data.get("content") or ""
        return ""

    def _think_minimax_anthropic(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
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
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if not resp.ok:
            body = (resp.text or "").strip()
            raise RuntimeError(f"MiniMax Token Plan request failed ({resp.status_code}): {body[:500]}")
        data = resp.json()
        blocks = data.get("content", []) if isinstance(data, dict) else []
        texts: List[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                if text:
                    texts.append(text)
        if texts:
            return "\n".join(texts).strip()
        if isinstance(data, dict) and isinstance(data.get("output_text"), str):
            return data.get("output_text") or ""
        return ""

    def _think_qveris(self, messages: List[Dict[str, str]], temperature: float = 0) -> Optional[str]:
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
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            error_msg = data.get("error_message") or "Unknown error"
            raise RuntimeError(f"Qveris execution failed: {error_msg}")
        tool_result = data.get("result", {}).get("data", {})
        content = ""
        if isinstance(tool_result, dict):
            choices = tool_result.get("choices", [])
            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content", "")
        if not content and isinstance(tool_result, str):
            content = tool_result
        return content


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


def generate_historical_markdown(llm: "StoryAgentLLM", person: str) -> Optional[str]:
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


def extract_historical_figures(llm: "StoryAgentLLM", text: str) -> List[str]:
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
    filename = f"{person}.md"
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
