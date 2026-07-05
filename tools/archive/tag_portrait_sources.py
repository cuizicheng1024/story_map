#!/usr/bin/env python3
"""
标记 portraits_map.json 中肖像的来源。

策略（按确定性降序）：
1. 人名在 WIKIMEDIA_PORTRAITS 硬编码表中 → source="real", label="Wikimedia Commons 传世画像"
2. 文件是 SVG → source="ai", label="SVG 占位肖像"
3. 其余 → source="unknown", label=""  （需要人工确认）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PORTRAITS_MAP_PATH = REPO_ROOT / "data" / "corpus" / "portraits_map.json"
ACQUIRE_PORTRAITS_PATH = REPO_ROOT / "tools" / "build" / "acquire_portraits.py"


def load_wikimedia_names() -> set[str]:
    """从 acquire_portraits.py 提取 WIKIMEDIA_PORTRAITS 的键名。"""
    text = ACQUIRE_PORTRAITS_PATH.read_text(encoding="utf-8")
    # 从字典字面量中提取所有键
    in_dict = False
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("WIKIMEDIA_PORTRAITS"):
            in_dict = True
            continue
        if in_dict:
            if stripped == "}":
                break
            if stripped.startswith("#"):
                continue
            # 匹配 "孔子": "Confucius.jpg", 或 "孔子": (...)
            import re
            m = re.match(r'^"([^"]+)"\s*:', stripped)
            if m:
                names.add(m.group(1))
    return names


def main() -> int:
    if not PORTRAITS_MAP_PATH.exists():
        print(f"文件不存在: {PORTRAITS_MAP_PATH}", file=sys.stderr)
        return 1

    wikimedia_names = load_wikimedia_names()
    print(f"从 WIKIMEDIA_PORTRAITS 表提取到 {len(wikimedia_names)} 个维基来源人物")

    portraits_map = json.loads(PORTRAITS_MAP_PATH.read_text(encoding="utf-8"))

    tagged_real = 0
    tagged_ai = 0
    tagged_wiki = 0

    for name, entry in portraits_map.items():
        if not isinstance(entry, dict):
            print(f"跳过非对象条目: {name}", file=sys.stderr)
            continue

        filename = entry.get("file", "")
        ext = Path(filename).suffix.lower() if filename else ""

        # SVG 占位图 → AI
        if ext == ".svg":
            entry["source"] = "ai"
            entry["source_label"] = "SVG 占位肖像"
            tagged_ai += 1
            continue

        # 在维基表中 → 真实画像
        if name in wikimedia_names:
            entry["source"] = "real"
            entry["source_label"] = "Wikimedia Commons 传世画像"
            tagged_real += 1
            continue

        # 维基别名匹配（如 "阿尔伯特·爱因斯坦" ←→ "爱因斯坦"）
        matched = False
        for wiki_name in wikimedia_names:
            # 全名包含简称或简称被全名包含
            if wiki_name in name or name in wiki_name:
                entry["source"] = "real"
                entry["source_label"] = f"Wikimedia Commons（别名: {wiki_name}）"
                tagged_wiki += 1
                matched = True
                break
            # 去掉 · 后的名进行比较（如 "卡尔·马克思" vs "马克思"）
            wiki_short = wiki_name.split("·")[-1] if "·" in wiki_name else wiki_name
            name_short = name.split("·")[-1] if "·" in name else name
            if wiki_short == name_short or (len(wiki_short) >= 2 and wiki_short in name_short) or (len(name_short) >= 2 and name_short in wiki_short):
                entry["source"] = "real"
                entry["source_label"] = f"Wikimedia Commons（别名: {wiki_name}）"
                tagged_wiki += 1
                matched = True
                break

        if matched:
            continue

        # 其余标记为 AI（因为 acquire_portraits 的主流程中，非 Wiki 的一律走 API 生成）
        entry["source"] = "ai"
        entry["source_label"] = "MiniMax AI 生成"
        tagged_ai += 1

    # 写回
    PORTRAITS_MAP_PATH.write_text(
        json.dumps(portraits_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    total = len(portraits_map)
    print(f"\n=== 标记结果 ===")
    print(f"  总计:      {total}")
    print(f"  真实画像:  {tagged_real + tagged_wiki} (Wikimedia Commons)")
    print(f"    - 精确匹配: {tagged_real}")
    print(f"    - 别名匹配: {tagged_wiki}")
    print(f"  AI 生成:   {tagged_ai} (MiniMax API)")
    print(f"\n已写入: {PORTRAITS_MAP_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
