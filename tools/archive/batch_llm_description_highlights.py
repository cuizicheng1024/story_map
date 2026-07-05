"""LLM 智能标注人物描述中的关键短语。

对每个人物的「生平概述」，由 LLM 识别 2-4 个真正值得高亮的短语（事件/转折/作品/关键地点/关键时间），
输出到 description_highlights.json，供模板渲染时使用，替代原先的正则高亮。

用法：
    python3 tools/batch_llm_description_highlights.py

输出：data/description_highlights.json
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
STORY_DIR = ROOT / "storymap" / "examples" / "story"
OUTPUT_FILE = ROOT / "data" / "description_highlights.json"
WORKERS = 2

SYSTEM_PROMPT = """你是历史人物传记标注专家。

你的任务：对一段人物生平概述文本，识别其中 2-4 个真正承载信息量的关键短语。

判断标准：
- **值得标注的**：决定人物命运的事件（如"安史之乱"、"永王李璘幕府"）、关键转折（如"遭谗去朝"、"遇赦东归"）、对自己或时代有重大影响的节点、重要的作品名、关键地点、关键人物
- **不值得标注的**：泛化标签（如"诗人"、"文学家"、"政治家"）、常用过渡词、纯粹的时间数字、整句话都是废话的描述性形容词
- 宁缺毋滥：如果一段描述中没有真正值得突出的内容，返回空列表

分类标签（category）：
- "event"：历史事件、人生大事（安史之乱、永王李璘幕府、供奉翰林、长流夜郎）
- "turning"：命运转折点（遭谗去朝、遇赦东归）
- "work"：作品名（将进酒、静夜思、蜀道难）
- "place"：关键地点（碎叶城、长安、金陵）
- "time"：有特殊含义的时间段（天宝元年、少年时期）— 不是随意一个年份

输出格式：JSON 数组，每个元素为 {"phrase": "短语原文", "category": "分类标签"}
只输出 JSON，不要任何额外文字。"""


def _load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _llm_chat(api_key: str, model: str, messages: list, base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload: dict = {"model": model, "messages": messages, "temperature": 0.3, "stream": False}
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", []) if isinstance(data, dict) else []
            if not choices:
                return ""
            msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
            return str((msg or {}).get("content") or "")
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                return ""


def extract_overview(md_path: Path) -> Optional[str]:
    """从 markdown 文件中提取「生平概述」段落"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"###\s*生平概述\s*\n+(.+)", text)
    if not m:
        return None
    raw = m.group(1)
    # 取到下一个 ## 或 ### 或文件结束
    end_match = re.search(r"\n#{2,3}\s", raw)
    if end_match:
        raw = raw[: end_match.start()]
    return raw.strip()


def annotate(person: str, overview: str, api_key: str, model: str, base_url: str) -> List[Dict[str, str]]:
    """调用 LLM 标注"""
    user_prompt = f"人物：{person}\n\n生平概述：\n{overview}"
    text = _llm_chat(api_key, model, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], base_url)

    # 解析 JSON 输出
    if not text.strip():
        return []

    # 剥离 MiniMax-M3 的 <think> 推理块
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # 尝试多种解析方式
    text = text.strip()
    # 去掉 markdown 代码块包裹
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试提取 [...] 部分
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            result = json.loads(m.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


def main():
    _load_env()
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL_ID", "MiniMax-M3")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.minimaxi.com/v1")

    if not api_key:
        print("ERROR: MINIMAX_API_KEY not set in .env")
        sys.exit(1)

    # 收集所有人物和描述
    tasks = []
    for md_path in sorted(STORY_DIR.glob("*.md")):
        person = md_path.stem
        overview = extract_overview(md_path)
        if overview and len(overview) >= 20:
            tasks.append((md_path, person, overview))

    # 加载已有结果（支持断点续跑）
    existing = {}
    if OUTPUT_FILE.exists():
        existing = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        print(f"已加载 {len(existing)} 条已有结果")

    remaining = [(p, o) for _, p, o in tasks if p not in existing or (isinstance(existing.get(p), list) and len(existing[p]) == 0)]
    print(f"共 {len(tasks)} 人，已完成(有高亮) {sum(1 for v in existing.values() if isinstance(v, list) and len(v) > 0)}，剩余 {len(remaining)}")

    if not remaining:
        print("全部完成")
        return

    lock = __import__("threading").Lock()
    done = {"count": len(existing)}

    def process_one(person: str, overview: str) -> tuple:
        result = annotate(person, overview, api_key, model, base_url)
        with lock:
            existing[person] = result
            done["count"] += 1
            if done["count"] % 20 == 0:
                # 定期保存
                OUTPUT_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  进度: {done['count']}/{len(tasks)} (已保存)")
        return person, result

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process_one, p, o): p for p, o in remaining}
        for future in as_completed(futures):
            try:
                person, highlights = future.result()
                if highlights:
                    print(f"  {person}: {len(highlights)} 个高亮 → {[h['phrase'] for h in highlights]}")
                else:
                    print(f"  {person}: 无高亮")
            except Exception as e:
                print(f"  ERROR {futures[future]}: {e}")

    # 最终保存
    OUTPUT_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成！共 {len(existing)} 人，保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
