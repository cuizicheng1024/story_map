"""
用 LLM 从人物 Markdown 中提取人际关系。

用法：
    # 测试少数几个人物
    python tools/build/extract_relations_llm.py --only 李白,杜甫,苏轼

    # 全量运行
    python tools/build/extract_relations_llm.py

输出文件：data/corpus/people_relations_llm.json
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


SYSTEM_PROMPT = """你是严谨的历史人物关系抽取器。给定一个人物的生平 Markdown 和一个"可关联人物列表"，提取该人物在文中明确提到的、且名字出现在该列表中的人际关系。

关系类型（label）严格限定为以下之一：
- 亲属（父亲、母亲、祖父、祖母、兄长、弟弟、姐姐、妹妹、子女、配偶——统称为"亲属"）
- 师承
- 亲友
- 同僚（同朝为官的大臣/官员之间）
- 盟友
- 对手/政敌
- 君臣（该人物与其君主/皇帝的关系。君主不可标注为"同僚"）

规则：
1. 只提取文中明确出现的人名，不要编造。
2. 只提取真实历史人物，忽略虚构角色（如小说人物）。
3. 每个人名必须完整（2-4个汉字，或完整的外国译名）。
4. 同一个关系人只出现一次，取最重要的关系类型。
5. 君主/皇帝与臣子的关系应标注为"君臣"，不可标注为"同僚"。
6. 【最重要】只从给定的"可关联人物列表"中选择关系人。如果文中提到某人但不在列表中，不要纳入结果。
7. 只返回严格 JSON，不要输出多余文字。

输出格式：
{"relations": [{"name": "杜甫", "label": "亲友"}, {"name": "苏辙", "label": "亲属"}]}"""


def _ask_relations(api_key: str, model: str, base_url: str, person: str, md_text: str, people_names: set) -> List[Dict[str, str]]:
    # 截取前 8000 字符，足够覆盖生平信息和主要事迹
    truncated = md_text[:8000]
    # 人名列表（去重排序，方便 LLM 检索）
    name_list_str = "、".join(sorted(people_names))
    user_prompt = f"人物：{person}\n\n可关联人物列表：{name_list_str}\n\nMarkdown 内容：\n{truncated}"
    text = _llm_chat(
        api_key, model,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        base_url,
    )
    text = text.strip()
    # 去除 <think>...</think> 推理块
    text = re.sub(r"<think\b[^>]*>[\s\S]*?</think>", "", text, flags=re.I)
    # 提取 JSON 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    else:
        # 尝试找纯 JSON 对象
        m = re.search(r'\{[\s\S]*"relations"[\s\S]*\}', text)
        if m:
            text = m.group(0).strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.I | re.M).strip()
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return []
        relations = obj.get("relations", [])
        if not isinstance(relations, list):
            return []
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        valid_labels = {"亲属", "师承", "亲友", "同僚", "盟友", "对手/政敌", "君臣"}
        for r in relations:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            label = str(r.get("label") or "").strip()
            if not name or not label:
                continue
            if label not in valid_labels:
                continue
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "label": label})
        return out
    except Exception:
        return []


def _normalize_person_name(name: str, people_names: set) -> Optional[str]:
    """尝试将 LLM 输出的名字匹配到 people 表中的标准名。"""
    name = str(name or "").strip()
    if not name:
        return None
    # 精确匹配
    if name in people_names:
        return name
    # 尝试常见变体
    variants = [
        name,
        "唐" + name,
        "明" + name,
        "宋" + name,
        "汉" + name,
        "清" + name,
        "周" + name,
        "秦" + name,
        "晋" + name,
    ]
    for v in variants:
        if v in people_names:
            return v
    # 相反：去掉朝代前缀
    for prefix in ("唐", "明", "宋", "汉", "清", "周", "秦", "晋", "元", "隋", "魏", "吴", "蜀"):
        if name.startswith(prefix) and name[len(prefix):] in people_names:
            return name[len(prefix):]
    # 模糊匹配：name 是 people_name 的子串 或 反之
    for pn in people_names:
        if name in pn or pn in name:
            return pn
    return None


def _merge_relations_into_db(root: Path) -> int:
    import sqlite3

    llm_path = root / "data" / "corpus" / "people_relations_llm.json"
    db_path = root / "data" / "people_knowledge.db"

    if not llm_path.exists():
        print(f"ERROR: {llm_path} not found. Run extraction first.")
        return 1
    if not db_path.exists():
        print(f"ERROR: {db_path} not found.")
        return 1

    llm_data = json.loads(llm_path.read_text(encoding="utf-8"))
    if not isinstance(llm_data, dict):
        print("ERROR: invalid JSON format")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # 加载 people 表中所有名称（用于匹配）
    rows = conn.execute("SELECT name FROM people").fetchall()
    people_names = {row[0] for row in rows if row[0]}

    upserted = 0
    skipped = 0
    for person, relations in llm_data.items():
        if not isinstance(relations, list):
            continue
        person_normalized = _normalize_person_name(person, people_names)
        if not person_normalized:
            skipped += 1
            continue

        for r in relations:
            if not isinstance(r, dict):
                continue
            target = str(r.get("name") or "").strip()
            label = str(r.get("label") or "").strip()
            if not target or not label:
                continue
            target_normalized = _normalize_person_name(target, people_names)
            if not target_normalized:
                continue
            if person_normalized == target_normalized:
                continue

            # 保持 source <= target
            src, tgt = person_normalized, target_normalized
            if src > tgt:
                src, tgt = tgt, src

            # 检查是否已存在 manual 关系（manual 优先，不覆盖）
            existing = conn.execute(
                "SELECT origin, relationship FROM relationships WHERE source_person = ? AND target_person = ?",
                (src, tgt),
            ).fetchone()
            if existing and existing[0] == "manual":
                # 已有手动标注的关系，跳过
                continue

            # 中文关系类型转英文标签（保持与现有 DB 一致）
            # 直接用中文 label 作为 relationship 字段
            conn.execute(
                """
                INSERT INTO relationships (source_person, target_person, origin, relationship, weight, evidence)
                VALUES (?, ?, 'bio', ?, 2, 'LLM 自动提取')
                ON CONFLICT(source_person, target_person) DO UPDATE SET
                    origin = 'bio',
                    relationship = excluded.relationship,
                    weight = 2,
                    evidence = 'LLM 自动提取',
                    updated_at = datetime('now')
                """,
                (src, tgt, label),
            )
            upserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    conn.close()

    print(f"Merged {upserted} relations into DB")
    print(f"Skipped {skipped} persons (no match in people table)")
    print(f"Total relations in DB: {total}")
    return 0


def main() -> int:
    root = _repo_root()
    _load_env_file(root / ".env")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default="", help="comma-separated person names to test")
    parser.add_argument("--merge-db", action="store_true", help="merge LLM cache into SQLite")
    parser.add_argument("--workers", type=int, default=5, help="number of concurrent LLM calls")
    args = parser.parse_args()

    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    base_url = (os.environ.get("LLM_BASE_URL") or "https://api.minimaxi.com/v1").strip()
    model = (os.environ.get("LLM_MODEL_ID") or "MiniMax-M3").strip()

    import sqlite3

    if args.merge_db:
        return _merge_relations_into_db(root)
    if not api_key:
        raise SystemExit("missing LLM_API_KEY")

    story_dir = root / "storymap" / "examples" / "story"

    # 收集需处理的人物
    all_names = sorted(
        [p.stem for p in story_dir.glob("*.md") if p.is_file()],
        key=lambda n: n,
    )
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if only:
        names = [n for n in all_names if n in set(only)]
    else:
        names = all_names

    if not names:
        print("No matching persons found.")
        return 1

    out_path = root / "data" / "corpus" / "people_relations_llm.json"
    # 加载已有缓存
    cache: Dict[str, List[Dict[str, str]]] = {}
    if out_path.exists():
        try:
            cache = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # 加载所有人名（用于 LLM 边界收敛 + 后置过滤）
    people_names = set(all_names)

    # 过滤已缓存的人物
    pending = [n for n in names if n not in cache]
    if not pending:
        print(f"All {len(names)} persons already cached.")
        return 0
    print(f"Cached: {len(names) - len(pending)}, Pending: {len(pending)}, Workers: {args.workers}")

    lock = threading.Lock()
    completed = [0]  # mutable counter for thread-safe progress

    def _process_one(name: str) -> Optional[tuple]:
        time.sleep(random.random() * 0.8)  # jitter to avoid rate limit
        md_path = story_dir / f"{name}.md"
        if not md_path.exists():
            return None
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        relations = _ask_relations(api_key, model, base_url, name, md_text, people_names)
        relations = [r for r in relations if _normalize_person_name(r['name'], people_names)]
        with lock:
            completed[0] += 1
            i = completed[0]
            print(f"[{i}/{len(pending)}] {name} -> {len(relations)} relations: {', '.join(r['name'] for r in relations[:6])}" + ("..." if len(relations) > 6 else ""))
            cache[name] = relations
            # 每 20 个增量写盘
            if i % 20 == 0:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return (name, relations)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_process_one, name): name for name in pending}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{name}] ERROR: {e}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nDone. Total {len(cache)} persons written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
