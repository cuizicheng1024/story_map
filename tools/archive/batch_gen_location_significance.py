"""批量用 LLM 为所有人物 Markdown 的每个地点生成个性化“历史意义”。

步骤：
1. 解析所有 Markdown，提取每个 ### 📍 重要地点 区块
2. 对没有 **意义** 字段的区块，调用 LLM 生成
3. 将意义插回 Markdown 原位置

用法：
    python3 tools/batch_gen_location_significance.py
"""

import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parents[1]
STORY_DIR = ROOT / "storymap" / "examples" / "story"

WORKERS = 5

SYSTEM_PROMPT = """你是历史人物个人史与地理意义分析专家。

你将收到一段人物 Markdown，其中包含若干 ### 📍 重要地点 区域的**完整原文**。对其中每个地点，你需要输出一句概括该地点对该人物**不可替代的历史意义**（40-80字）。

写作要求：
1. 深度关联人物命运：指出该地点在人物人生中扮演了怎样独一无二的角色（转折点、巅峰、低谷、起点等）。
2. 拒绝泛泛而谈：不要说“是理解该人物的重要地点”这种套话。要具体——发生了什么、改变了什么。
3. 有温度、有画面感：像历史随笔，而不是工具书。
4. 输出格式：每个地点一行，用“地点名：意义”的格式，按原文顺序输出。不要编号，不要多余文字。

示例：
蜀中青莲乡：李白少年读书习剑的故土，蜀中山水赋予了他'五岳寻仙不辞远'的游仙气质，是所有浪漫想象的起点。
长安（被赐金放还）：供奉翰林的荣耀与赐金放还的落寞于此交汇——长安的城门关闭后，世上少了一个御用文人，多了一个永不安协的诗仙。
浔阳：永王兵败后被捕下狱的囚困之地——从'千里江陵一日还'的轻快变为'大鹏飞兮振八裔'的悲鸣，诗仙的生命乐章在此从快板滑入哀歌。"""


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
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.3, "stream": False}
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
                print(f"  LLM FAILED: {e}", file=sys.stderr)
                return ""


def parse_locations_from_md(md_path: Path) -> List[Dict]:
    """解析 Markdown 中的 ### 📍 重要地点 区块，返回位置列表。"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    person = md_path.stem

    # Split by ### headers
    # Each location block starts with ### 📍 重要地点： or similar
    blocks = re.split(r"(?=^###\s+(?:📍\s*)?重要地点[：:])", text, flags=re.MULTILINE)
    if len(blocks) <= 1:
        return []
    blocks = blocks[1:]  # skip before first location header

    locations = []
    for block in blocks:
        # Extract location name from header
        header = block.split("\n")[0]
        loc_name = re.sub(r"^###\s+(?:📍\s*)?重要地点[：:]\s*", "", header).strip()
        # Clean markdown bold markers from name
        loc_name = re.sub(r"\*\*([^*]+)\*\*", r"\1", loc_name)

        # Extract fields
        year = ""
        m = re.search(r"[-*]\s*\*\*公元纪年\*\*\s*[：:]\s*(.+)", block)
        if m:
            year = m.group(1).strip()

        position = ""
        m = re.search(r"[-*]\s*\*\*位置\*\*\s*[：:]\s*(.+)", block)
        if m:
            position = m.group(1).strip()

        event = ""
        m = re.search(r"[-*]\s*\*\*事迹\*\*\s*[：:]\s*(.+)", block)
        if m:
            event = m.group(1).strip()

        if not event and not position:
            # Alternative format: just **事件** or plain text
            m = re.search(r"[-*]\s*\*\*事件\*\*\s*[：:]\s*(.+)", block)
            if m:
                event = m.group(1).strip()

        # Already has significance?
        has_sig = bool(re.search(r"[-*]\s*\*\*意义\*\*\s*[：:]", block))
        if has_sig:
            continue

        locations.append({
            "person": person,
            "name": loc_name,
            "year": year,
            "position": position,
            "event": event,
            "block": block.strip(),
        })

    return locations


def generate_significances(person: str, locations: List[Dict], api_key: str, model: str, base_url: str) -> Dict[str, str]:
    """返回 {location_name: significance} 字典。"""
    # Build the context
    lines = []
    for loc in locations:
        lines.append(f"### {loc['name']}")
        if loc["year"]:
            lines.append(f"时间：{loc['year']}")
        if loc["position"]:
            lines.append(f"位置：{loc['position']}")
        if loc["event"]:
            lines.append(f"事件：{loc['event']}")
        lines.append("")
    
    context = "\n".join(lines)
    user_prompt = f"人物：{person}\n\n地点列表：\n{context}"

    text = _llm_chat(api_key, model, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], base_url)

    # Parse response: each line is "地点名：意义"
    results = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        # Remove numbering like "1. " or "1、"
        line = re.sub(r"^\d+[\.\、\)\s]+", "", line)
        if "：" in line:
            name, sig = line.split("：", 1)
        elif ":" in line:
            name, sig = line.split(":", 1)
        else:
            continue
        name = name.strip()
        sig = sig.strip().rstrip("。；;，,")
        if len(sig) >= 15:  # meaningful significance
            results[name] = sig

    return results


def apply_significances(md_path: Path, all_locations: List[Dict], all_sigs: Dict[str, str]):
    """将生成的意义写回 Markdown 文件。"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    modified = False
    for loc in all_locations:
        sig = all_sigs.get(loc["name"], "")
        if not sig:
            continue

        block = loc["block"]
        # Find the exact block in the file
        idx = text.find(block)
        if idx < 0:
            # Try fuzzy match - find by location name
            pattern = re.escape(f"### 📍 重要地点：{loc['name']}")
            # Also try without emoji
            pattern2 = re.escape(f"### 重要地点：{loc['name']}")
            m = re.search(pattern, text)
            if not m:
                m = re.search(pattern2, text)
            if not m:
                continue
            # Find the end of this block (next ### or end of file)
            block_start = m.start()
            rest = text[block_start:]
            next_section = re.search(r"\n###\s", rest[5:])  # skip past header
            if next_section:
                block_end = block_start + 5 + next_section.start()
                block = text[block_start:block_end]
            else:
                block = rest
        else:
            block_start = idx
            block_end = idx + len(block)

        # Find insertion point: after the last field line before next ### or next location
        # Insert **意义** before next heading or end of block
        insert_pattern = r"(\n)(?=\n*###|$)"
        
        # Simpler approach: insert after the last non-empty line of the block
        lines = block.split("\n")
        new_lines = []
        inserted = False
        for i, line in enumerate(lines):
            new_lines.append(line)
            # Insert after event line (or last field)
            if not inserted:
                is_event = line.startswith("- **事迹**") or line.startswith("- **事件**")
                is_position = line.startswith("- **位置**")
                is_time = line.startswith("- **公元纪年**") or line.startswith("- **公元时间**")
                
                # Check if next line is empty or starts new section
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                is_end = (not next_line.strip() or next_line.startswith("###") or 
                         next_line.startswith("- **地点") or next_line.startswith("- **时间"))

                if is_event or (is_position and is_end):
                    new_lines.append(f"- **意义**：{sig}")
                    inserted = True

        if inserted:
            new_block = "\n".join(new_lines)
            text = text[:block_start] + new_block + text[block_end:]
            modified = True

    if modified:
        md_path.write_text(text, encoding="utf-8")
        return True
    return False


def main():
    _load_env()

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "https://api.minimaxi.com/v1").strip()
    model = os.environ.get("LLM_MODEL_ID", "MiniMax-M3").strip()

    if not api_key:
        print("ERROR: missing LLM_API_KEY", file=sys.stderr)
        return 1

    # 1. Parse all locations from all markdowns
    all_persons_locations: Dict[str, Tuple[Path, List[Dict]]] = {}
    total_locs = 0
    for md_path in sorted(STORY_DIR.glob("*.md")):
        locs = parse_locations_from_md(md_path)
        if locs:
            all_persons_locations[md_path.stem] = (md_path, locs)
            total_locs += len(locs)

    print(f"共 {len(all_persons_locations)} 人需要补充意义，总计 {total_locs} 个地点")
    print(f"并发数: {WORKERS}")
    print()

    # 2. Batch generate with LLM
    lock = threading.Lock()
    completed = [0]
    sig_applied = [0]
    t0 = time.time()
    persons_processed = list(all_persons_locations.keys())
    total_persons = len(persons_processed)

    def _process(person: str):
        md_path, locations = all_persons_locations[person]
        try:
            sigs = generate_significances(person, locations, api_key, model, base_url)
            if sigs:
                written = apply_significances(md_path, locations, sigs)
                with lock:
                    completed[0] += 1
                    if written:
                        sig_applied[0] += 1
                    i = completed[0]
                    matched = len(sigs)
                    total = len(locations)
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (total_persons - i) / rate if rate > 0 else 0
                    print(f"[{i}/{total_persons}] {person}: {matched}/{total} sigs generated, written={written} | {rate:.2f}/s | ETA={eta:.0f}s")
            else:
                with lock:
                    completed[0] += 1
                    print(f"[{completed[0]}/{total_persons}] {person}: FAILED (no sigs returned)")
        except Exception as e:
            with lock:
                completed[0] += 1
                print(f"[{completed[0]}/{total_persons}] {person}: EXCEPTION: {e}")

    persons_sorted = sorted(persons_processed, key=lambda p: len(all_persons_locations[p][1]), reverse=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_process, p): p for p in persons_sorted}
        for future in as_completed(futures):
            p = futures[future]
            try:
                future.result()
            except Exception as e:
                with lock:
                    completed[0] += 1
                print(f"[{completed[0]}/{total_persons}] {p}: FUTURE EXCEPTION: {e}")

    elapsed = time.time() - t0
    print(f"\n完成: {sig_applied[0]}/{total_persons} 人已写入意义, 耗时 {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
