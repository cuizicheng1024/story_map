"""故事生成代理 — 提示词管理、人物提取、Markdown 生成。

LLM 客户端见 llm_client.py。
"""
import json
import os
import re
from typing import List, Optional

from .llm_client import (
    LLMRequestError,
    StoryAgentLLM,
    _classify_request_exception,
    _message_stats,
    _safe_excerpt,
    _validate_person,
)
from ..core.env_utils import load_project_env
from ..core.text_utils import strip_reasoning_blocks
from ..core.project_paths import classify_story_person_authenticity, project_root_path
from ..runtime.legacy_agent import graph as story_agent_graph_utils
from ..runtime.legacy_agent import runtime as story_agent_runtime_utils


load_project_env(from_file=__file__, override=False)


def _is_plausible_person_name(text: str) -> bool:
    """检查字符串是否看起来像一个合理的人名（非LLM垃圾输出）。"""
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > 20:
        return False
    # 包含过多英文单词（空格分隔）的不是中文系统期望的人名
    if len(cleaned.split()) > 3:
        return False
    # 包含特殊标点的不是人名
    if re.search(r"[?？!！。:：；;（）()\[\]{}<>/\\]", cleaned):
        return False
    return True


def _read_prompt(relpath: str) -> str:
    """
    读取 docs/ 目录下的提示词文件内容。
    """
    rel = str(relpath or "").strip()
    if not rel:
        raise FileNotFoundError("prompt path is empty")
    root = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(project_root_path(), "storymap", "docs", rel),
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
    # Defense in depth: strip reasoning blocks even if upstream forgot to.
    raw = strip_reasoning_blocks(raw)
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            names = [str(x).strip() for x in data if str(x).strip()]
            return list(dict.fromkeys(names))
    except Exception:
        pass
    # Try to extract the first JSON array block from the response, in case the
    # model wraps its JSON answer with surrounding prose.
    extracted = _extract_json_block(raw)
    if extracted and extracted != raw:
        try:
            data = json.loads(extracted)
            if isinstance(data, list):
                names = [str(x).strip() for x in data if str(x).strip()]
                if names:
                    if llm and hasattr(llm, "_emit"):
                        llm._emit("⚠️ 解析人物列表时剥离了包裹文本")
                    return list(dict.fromkeys(names))
        except Exception:
            pass
    # Last-resort fallback: a few Chinese models emit a single line of the
    # answer (e.g. "范蠡") after reasoning. Treat that single short line as
    # one candidate name rather than dumping the entire raw text downstream.
    fallback = raw.strip()
    lines = [line.strip().strip("，。；;、 []\"'") for line in fallback.splitlines() if line.strip()]
    if len(lines) == 1:
        candidate = lines[0]
        if 1 <= len(candidate) <= 12:
            print(f"⚠️ 解析人物列表失败，回退为单行候选: {candidate}")
            if llm and hasattr(llm, "_emit"):
                llm._emit(f"⚠️ 解析人物列表回退为单行候选: {candidate}")
            return [candidate]
    error_text = ""
    try:
        json.loads(fallback)
    except Exception as e:
        error_text = str(e)
    print(f"⚠️ 解析人物列表失败 (JSON解析异常): {error_text}")
    if llm and hasattr(llm, "_emit"):
        llm._emit(f"⚠️ 解析人物列表失败: {error_text}")
    # 仅当 LLM 响应看起来像一个合理的人名时才作为回退值返回，
    # 防止把 LLM 的垃圾输出（如长句英文解释）误当成人名。
    if _is_plausible_person_name(fallback):
        return [fallback]
    return []


_JSON_BLOCK_ARRAY_RE = re.compile(r"\[\s*[\s\S]*?\]\s*")


def _extract_json_block(raw: str) -> str:
    """Pick the first balanced JSON array block from `raw`."""
    text = str(raw or "").strip()
    if not text:
        return text
    match = _JSON_BLOCK_ARRAY_RE.search(text)
    if match:
        candidate = match.group(0)
        # Round-trip through json.loads to ensure it is valid JSON before returning.
        try:
            parsed = json.loads(candidate)
        except Exception:
            return text
        if isinstance(parsed, list):
            return candidate
    return text


def save_markdown(person: str, content: str) -> str:
    """
    保存 Markdown 到 examples/story/ 目录，若存在则覆盖。
    在写入前自动剥离 LLM 推理思考块，防止 <think> 标签残留污染文件。
    """
    root = project_root_path()
    base = os.path.join(root, "storymap", "examples", "story")
    os.makedirs(base, exist_ok=True)
    safe_person = str(person or "").translate(str.maketrans({c: "_" for c in '\\/:*?"<>|'})).strip() or "map"
    filename = f"{safe_person}.md"
    path = os.path.join(base, filename)
    # 写入前剥离推理思考块，防止 <think> 标签残留
    clean_content = strip_reasoning_blocks(content)
    with open(path, "w", encoding="utf-8") as f:
        f.write(clean_content)
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
