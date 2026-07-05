"""批量用LLM生成所有缺失作品摘要（442个作品）。"""
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
STORY_DIR = ROOT / "storymap" / "examples" / "story"
OUT_PATH = ROOT / "data" / "corpus" / "work_summary_llm.json"

WORKERS = 5

SYSTEM_PROMPT = """你是严谨的文学作品信息抽取器。给定一个人物的生平 Markdown 和一个作品名，提取该作品的核心信息。

提取规则：
1. 如果 Markdown 中明确提到该人物创作/撰写了该作品，则 authors 填该人物名；如果只是被提及、收录、或引用，则 authors 留空。
2. one_liner 是对该作品的「一句话介绍」（30-80字），说明这是什么作品、核心内容是什么。不要写人物生平。
3. quotes 是该作品具有代表性的「原文名句」（1-3句），优先从 Markdown 中提取；如果 Markdown 中没有但你对这部作品很熟悉，也可以用你的知识提供，但必须确保是真实名句。
4. genre 推断该作品的体裁（如"诗""词""赋""散文""小说""论文""奏章""书信""序""传记""科学著作""条约""法典""碑文""曲谱""剧本""油画""雕塑""歌曲""组曲""宣言""演说""宪法""法案""数学著作""天文学著作""医学著作""地理著作""辞书""语录""传记""自传""回忆录""书信集""画作""壁画"等），不确定则留空。
5. era 为该作品创作的时代，如果人物 Markdown 有时代信息则用，否则留空。
6. quote_policy：如果 quotes 有内容填 "preferred"，否则填 "summary_only"。

只返回严格 JSON，不要输出多余文字。输出格式：
{"one_liner": "...", "genre": "...", "authors": ["..."], "quotes": ["..."], "era": "...", "quote_policy": "preferred"}"""


def _load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _llm_chat(api_key: str, model: str, messages: List[Dict], base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "api-key": api_key, "x-api-key": api_key}
    payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.0, "stream": False}
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=240)
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
                raise


def _ask_work_info(person: str, work_title: str, md_text: str, api_key: str, model: str, base_url: str) -> Optional[Dict]:
    truncated = md_text[:8000]
    user_prompt = f"人物：{person}\n作品：《{work_title}》\n\nMarkdown 内容：\n{truncated}"
    text = _llm_chat(api_key, model, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], base_url)
    text = text.strip()
    text = re.sub(r"<think\b[^>]*>[\s\S]*?</think>", "", text, flags=re.I)
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    else:
        m = re.search(r'\{[\s\S]*"one_liner"[\s\S]*\}', text)
        if m:
            text = m.group(0).strip()
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return None
        return {
            "one_liner": str(obj.get("one_liner") or "").strip(),
            "genre": str(obj.get("genre") or "").strip(),
            "authors": [str(x).strip() for x in obj.get("authors") or [] if str(x).strip()],
            "quotes": [str(x).strip() for x in obj.get("quotes") or [] if str(x).strip()],
            "era": str(obj.get("era") or "").strip(),
            "quote_policy": str(obj.get("quote_policy") or "summary_only").strip(),
        }
    except Exception:
        return None


def get_missing_works() -> List[tuple]:
    """返回 (person, work_title) 的缺失任务列表"""
    # 加载 people summary
    with open(ROOT / "data" / "corpus" / "people_summary_index.json", encoding="utf-8") as f:
        psi = json.load(f)
    items = psi.get("items", {})

    # 加载现有 LLM 缓存
    cache: Dict = {}
    if OUT_PATH.exists():
        cache = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    tasks = []
    for person, info in items.items():
        works = info.get("works", [])
        for w in works:
            if w not in cache:
                md_path = STORY_DIR / f"{person}.md"
                if md_path.exists():
                    tasks.append((person, w))
    return tasks


def main():
    _load_env()

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "https://api.minimaxi.com/v1").strip()
    model = os.environ.get("LLM_MODEL_ID", "MiniMax-M3").strip()

    if not api_key:
        print("ERROR: missing LLM_API_KEY", file=sys.stderr)
        return 1

    tasks = get_missing_works()
    total = len(tasks)
    if not tasks:
        print("No tasks — all works have LLM summaries.")
        return 0

    print(f"需生成摘要: {total} 个作品")
    print(f"并发数: {WORKERS}")

    # 加载现有缓存
    cache: Dict = {}
    if OUT_PATH.exists():
        cache = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    lock = threading.Lock()
    completed = [0]
    success = [0]
    t0 = time.time()

    def _process(person: str, work_title: str):
        time.sleep(0.1 + (hash(work_title) % 100) * 0.01)  # jitter
        md_path = STORY_DIR / f"{person}.md"
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        result = _ask_work_info(person, work_title, md_text, api_key, model, base_url)
        with lock:
            completed[0] += 1
            i = completed[0]
            if result:
                cache[work_title] = result
                success[0] += 1
                ol = result["one_liner"][:50]
                qc = len(result.get("quotes", []))
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                print(f"[{i}/{total}] {person}/{work_title} | {ol}... | quotes={qc} | {rate:.1f}/s | ETA={eta:.0f}s")
            else:
                print(f"[{i}/{total}] {person}/{work_title} | FAILED")
            # auto-save every 20
            if i % 20 == 0:
                OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(OUT_PATH, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_process, p, w): (p, w) for p, w in tasks}
        for future in as_completed(futures):
            p, w = futures[future]
            try:
                future.result()
            except Exception as e:
                with lock:
                    completed[0] += 1
                print(f"[{completed[0]}/{total}] {p}/{w} | EXCEPTION: {e}")

    # Final save
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f"\n完成: {success[0]}/{total} 成功, 耗时 {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
