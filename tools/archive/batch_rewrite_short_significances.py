"""批量重写过短(<20字)的地点历史意义。

与 batch_gen_location_significance.py 不同：本脚本只处理已有意义但过短的，用LLM扩写。

用法：
    python3 tools/batch_rewrite_short_significances.py
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
WORKERS = 3
MIN_SIG_LEN = 30  # 短于这个长度就需要重写

SYSTEM_PROMPT = """你是历史人物个人史与地点意义分析专家。

你将收到一个人物的若干条已有"历史意义"（每条不足20字），需要你把它们扩展为40-80字、有文采、有深度的个性化历史意义。

写作要求：
1. 保持原意的核心信息，但要加入具体的历史细节、人物命运转折的暗示
2. 拒绝套话：不要说"是理解该人物的重要地点"这类废话。要说发生了什么、改变了什么
3. 语言风格要有温度、有画面感，像历史随笔，不是工具书
4. 用中文，不要用英文或编号

只返回每个地点的扩展后意义，一行一个，格式为"地点名：意义"。不要输出多余文字。"""


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
                return ""


def get_short_sigs() -> List[Tuple[Path, str, List[Tuple[str, str, int]]]]:
    """返回 [(md_path, person, [(loc_name, old_sig, char_pos), ...])]"""
    results = []
    sig_pattern = re.compile(r"^(?:- )?\*\*意义\*\*[：:]\s*(.+)", re.MULTILINE)

    for md_path in sorted(STORY_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        person = md_path.stem

        short_list = []
        for m in sig_pattern.finditer(text):
            sig = m.group(1).strip()
            if len(sig) < MIN_SIG_LEN and len(sig) >= 3:
                # Find the associated location name (look backward for "重要地点：XXX")
                before = text[: m.start()]
                loc_match = re.search(r"###\s+(?:📍\s*)?重要地点[：:]\s*(.*?)$", before, re.MULTILINE)
                loc_name = loc_match.group(1).strip() if loc_match else "未知地点"
                # Clean bold markers
                loc_name = re.sub(r"\*\*([^*]+)\*\*", r"\1", loc_name)
                short_list.append((loc_name, sig, m.start()))

        if short_list:
            results.append((md_path, person, short_list))

    return results


def expand_sigs(person: str, short_sigs: List[Tuple[str, str, int]], api_key: str, model: str, base_url: str) -> Dict[str, str]:
    """返回 {loc_name: expanded_sig}"""
    lines = []
    for loc_name, old_sig, _ in short_sigs:
        lines.append(f"地点：{loc_name} — 当前意义：{old_sig}")

    context = "\n".join(lines)
    user_prompt = f"人物：{person}\n\n待扩展：\n{context}"

    text = _llm_chat(api_key, model, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], base_url)

    results = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        line = re.sub(r"^\d+[\.\、\)\s]+", "", line)
        if "：" in line:
            name, sig = line.split("：", 1)
        elif ":" in line:
            name, sig = line.split(":", 1)
        else:
            continue
        name = name.strip()
        sig = sig.strip().rstrip("。；;，,")
        if len(sig) >= MIN_SIG_LEN:
            results[name] = sig

    return results


def apply_expanded_sigs(md_path: Path, short_sigs: List[Tuple[str, str, int]], expanded: Dict[str, str]):
    """用扩展后的意义替换原文。按字符位置从后往前替换。"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    sig_line_pattern = re.compile(r"^[-*]\s*\*\*意义\*\*[：:]\s*.+", re.MULTILINE)

    applied = 0
    for loc_name, old_sig, pos in short_sigs:
        new_sig = expanded.get(loc_name, "")
        if not new_sig:
            continue

        # Find the exact line containing this old sig
        # Search near the original position
        window = text[max(0, pos - 60): pos + len(old_sig) + 80]
        m = sig_line_pattern.search(window)
        if m:
            old_line = m.group(0)
            new_line = f"- **意义**：{new_sig}"
            text = text.replace(old_line, new_line, 1)
            applied += 1

    if applied > 0:
        md_path.write_text(text, encoding="utf-8")
    return applied


def main():
    _load_env()

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "https://api.minimaxi.com/v1").strip()
    model = os.environ.get("LLM_MODEL_ID", "MiniMax-M3").strip()

    if not api_key:
        print("ERROR: missing LLM_API_KEY", file=sys.stderr)
        return 1

    tasks = get_short_sigs()
    total_sigs = sum(len(t[2]) for t in tasks)
    print(f"共 {len(tasks)} 人物, {total_sigs} 条过短意义 (< {MIN_SIG_LEN} 字)")
    print(f"并发: {WORKERS}")
    print()

    lock = threading.Lock()
    completed = [0]
    expanded_count = [0]
    t0 = time.time()

    def _process(md_path, person, short_sigs):
        try:
            expanded = expand_sigs(person, short_sigs, api_key, model, base_url)
            if expanded:
                written = apply_expanded_sigs(md_path, short_sigs, expanded)
                with lock:
                    completed[0] += 1
                    expanded_count[0] += written
                    i = completed[0]
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (len(tasks) - i) / rate if rate > 0 else 0
                    print(f"[{i}/{len(tasks)}] {person}: {len(short_sigs)}→{written} expanded | {rate:.2f}/s | ETA={eta:.0f}s")
            else:
                with lock:
                    completed[0] += 1
                    print(f"[{completed[0]}/{len(tasks)}] {person}: FAILED")
        except Exception as e:
            with lock:
                completed[0] += 1
                print(f"[{completed[0]}/{len(tasks)}] {person}: ERROR {e}")

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_process, md, person, sigs): person for md, person, sigs in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    elapsed = time.time() - t0
    print(f"\n完成: {expanded_count[0]} 条扩展, 耗时 {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
