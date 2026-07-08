"""
用 LLM 生成高质量作品 tooltip 信息。

用法：
    # 测试少数几个作品
    python tools/build/build_work_summary_llm.py --only 李白,苏轼 --works 静夜思,赤壁赋

    # 只补全缺少名句的作品（quotes 为空）
    python tools/build/build_work_summary_llm.py --no-quotes-only --limit 10

    # 只补全 one_liner 为人物生平介绍（非作品描述）的作品
    python tools/build/build_work_summary_llm.py --bio-only --limit 0

    # 对指定人物的所有作品
    python tools/build/build_work_summary_llm.py --only 李白 --limit 5

    # 组合过滤：指定人物 + 只补全人物生平 tooltip
    python tools/build/build_work_summary_llm.py --only 李白 --bio-only --limit 0

输出文件：data/corpus/work_summary_llm.json（增量更新）
"""

import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        os.environ.setdefault(k, v)


def _llm_chat(api_key: str, model: str, messages: List[Dict[str, str]], base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
        "x-api-key": api_key,
    }
    payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.0, "stream": False}
    last_err: Optional[Exception] = None
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
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err or RuntimeError("LLM request failed")


SYSTEM_PROMPT = """你是严谨的文学作品信息抽取器。给定一个人物的生平 Markdown 和一个作品名，提取该作品的核心信息。

提取规则：
1. 如果 Markdown 中明确提到该人物创作/撰写了该作品，则 authors 填该人物名；如果只是被提及、收录、或引用，则 authors 留空。
2. one_liner 是对该作品的「一句话介绍」（30-80字），说明这是什么作品、核心内容是什么。不要写人物生平。
3. quotes 是该作品具有代表性的「原文名句」（1-3句），优先从 Markdown 中提取；如果 Markdown 中没有但你对这部作品很熟悉，也可以用你的知识提供，但必须确保是真实名句。
4. genre 推断该作品的体裁（如"诗""词""赋""散文""小说""论文""奏章""奏疏""书信""序""传记""年谱""科学著作""数学著作"等），不确定则留空。
5. era 为该作品创作的时代，如果人物 Markdown 有时代信息则用，否则留空。
6. quote_policy：如果 quotes 有内容填 "preferred"，否则填 "summary_only"。

只返回严格 JSON，不要输出多余文字。输出格式：
{"one_liner": "...", "genre": "...", "authors": ["..."], "quotes": ["..."], "era": "...", "quote_policy": "preferred"}"""


def _ask_work_info(
    api_key: str,
    model: str,
    base_url: str,
    person: str,
    work_title: str,
    md_text: str,
) -> Optional[Dict[str, Any]]:
    truncated = md_text[:8000]
    user_prompt = f"人物：{person}\n作品：《{work_title}》\n\nMarkdown 内容：\n{truncated}"
    text = _llm_chat(
        api_key, model,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        base_url,
    )
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


def _is_person_bio_one_liner(one_liner: str) -> bool:
    """判断 one_liner 是否实际是人物生平介绍而非作品描述。"""
    if not one_liner:
        return False
    # 前30字符内出现人物生平标志词
    if re.search(r'(出生于|生于|原名|出身|，早年|出生于)', one_liner[:30]):
        return True
    # 开头为人名+（年份 的模式，如：鲁迅（1881—1936）
    if re.search(r'^.{2,4}（?\d{3,4}', one_liner):
        return True
    return False


def _is_literary_work(title: str, info: dict) -> bool:
    """判断是否为文学作品（排除绘画、雕塑、歌曲、条约、战役等）。"""
    ol = info.get("one_liner", "") or ""
    genre = info.get("genre", "") or ""
    combined = title + ol
    # 明确排除的类型
    exclude = ["画", "雕塑", "壁画", "音乐", "乐曲", "条约", "法案",
               "宪法", "宣言", "演说", "定理", "公式", "方程", "战役",
               "围困", "法典", "决议", "政变"]
    for w in exclude:
        if w in combined or w in genre:
            return False
    # 排除歌曲类
    if genre == "歌曲":
        return False
    # 排除科学类
    if "科学" in genre:
        return False
    return True


def main() -> int:
    root = _repo_root()
    _load_env_file(root / ".env")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default="", help="comma-separated person names")
    parser.add_argument("--works", type=str, default="", help="comma-separated specific work titles to test")
    parser.add_argument("--no-quotes-only", action="store_true", help="only fill works missing quotes")
    parser.add_argument("--bio-only", action="store_true", help="only fill works whose one_liner is a person bio (not work description)")
    parser.add_argument("--lit-only", action="store_true", help="with --bio-only: only literary works, skip paintings/sculptures/songs/treaties etc.")
    parser.add_argument("--workers", type=int, default=5, help="number of concurrent LLM calls")
    parser.add_argument("--limit", type=int, default=5, help="max works per person")
    args = parser.parse_args()

    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    base_url = (os.environ.get("LLM_BASE_URL") or "https://api.minimaxi.com/v1").strip()
    model = (os.environ.get("LLM_MODEL_ID") or "MiniMax-M3").strip()
    if not api_key:
        raise SystemExit("missing LLM_API_KEY")

    story_dir = root / "storymap" / "examples" / "story"
    existing_index_path = root / "data" / "corpus" / "work_summary_index.json"
    out_path = root / "data" / "corpus" / "work_summary_llm.json"

    # 加载现有 work_summary_index
    existing: Dict[str, Dict[str, Any]] = {}
    if existing_index_path.exists():
        raw = json.loads(existing_index_path.read_text(encoding="utf-8"))
        existing = raw.get("items", {}) if isinstance(raw, dict) else {}

    # 加载已有 LLM 缓存
    cache: Dict[str, Dict[str, Any]] = {}
    if out_path.exists():
        try:
            cache = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # 指定作品名直接测试
    specific_works = [w.strip() for w in args.works.split(",") if w.strip()]

    # 构建任务列表
    tasks: List[tuple] = []  # (person, work_title)
    only = [x.strip() for x in args.only.split(",") if x.strip()]

    if specific_works:
        for w in specific_works:
            if w in cache:
                continue
            # 找到这个作品属于哪个人物
            info = existing.get(w)
            if info:
                authors = info.get("authors") or []
                related = info.get("related_people") or []
                candidates = set(authors + related)
                for person in candidates:
                    md_path = story_dir / f"{person}.md"
                    if md_path.exists():
                        tasks.append((person, w))
            else:
                # fallback: try only persons
                for person in only or []:
                    tasks.append((person, w))
    elif only:
        for person in only:
            md_path = story_dir / f"{person}.md"
            if not md_path.exists():
                continue
            # 从 existing index 找该人物的作品
            person_works = sorted(
                [title for title, info in existing.items()
                 if person in (info.get("authors") or []) or person in (info.get("related_people") or [])],
            )
            if args.no_quotes_only:
                person_works = [w for w in person_works
                               if not (existing[w].get("quotes") or existing[w].get("quote"))]
            if args.bio_only:
                person_works = [w for w in person_works
                               if _is_person_bio_one_liner(existing[w].get("one_liner", ""))]
                if args.lit_only:
                    person_works = [w for w in person_works
                                   if _is_literary_work(w, existing[w])]
            for w in person_works[:int(args.limit)]:
                if w not in cache:
                    tasks.append((person, w))
    elif args.bio_only:
        # 全量扫描：找出所有 one_liner 是人物生平介绍的作品
        filter_desc = "person-bio one_liner"
        if args.lit_only:
            filter_desc += " (literary only)"
        print(f"Scanning for works with {filter_desc}...")
        for title, info in existing.items():
            if title in cache:
                continue
            if not _is_person_bio_one_liner(info.get("one_liner", "")):
                continue
            if args.lit_only and not _is_literary_work(title, info):
                continue
            # 找到这个作品属于哪个人物
            authors = info.get("authors") or []
            related = info.get("related_people") or []
            candidates = set(authors + related)
            found = False
            for person in candidates:
                md_path = story_dir / f"{person}.md"
                if md_path.exists():
                    tasks.append((person, title))
                    found = True
                    break
            if not found:
                # fallback: 作品名可能本身就是人名
                md_path = story_dir / f"{title}.md"
                if md_path.exists():
                    tasks.append((title, title))
        # limit 支持，0 = 不限制
        if int(args.limit) > 0:
            tasks = tasks[:int(args.limit)]
    else:
        print("Use --only to specify persons, or --works for specific works.")
        return 1

    if not tasks:
        print("No tasks to process.")
        return 0

    print(f"Total tasks: {len(tasks)}, Workers: {args.workers}")

    lock = threading.Lock()
    completed = [0]

    def _process_one(person: str, work_title: str) -> Optional[tuple]:
        time.sleep(random.random() * 0.8)  # jitter to avoid rate limit
        md_path = story_dir / f"{person}.md"
        if not md_path.exists():
            return None
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        result = _ask_work_info(api_key, model, base_url, person, work_title, md_text)
        with lock:
            completed[0] += 1
            i = completed[0]
            if result:
                cache[work_title] = result
                quotes_preview = ", ".join([q[:20] + "..." for q in result.get("quotes", [])])
                print(f"[{i}/{len(tasks)}] {person} / 《{work_title}》 -> one_liner={result['one_liner'][:40]}...  |  quotes={len(result.get('quotes', []))}")
            else:
                print(f"[{i}/{len(tasks)}] {person} / 《{work_title}》 -> FAILED")
            if i % 20 == 0:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return (work_title, result)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_process_one, person, work_title): (person, work_title) for person, work_title in tasks}
        for future in as_completed(futures):
            person, work_title = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{person} / 《{work_title}》] ERROR: {e}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nDone. {len(cache)} works written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
