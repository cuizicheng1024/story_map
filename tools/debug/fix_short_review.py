#!/usr/bin/env python3
"""为 short_review 为空的文件补充内容。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML_DIR = ROOT / "artifacts" / "story_map"

# 手工审核后的 short_review 内容
SHORT_REVIEWS = {
    "乐松生": "和平赎买",
    "亚历山大二世": "解放者沙皇",
    "哥伦布": "为上帝和国王陛下效力",
    "唐僖宗": "幸蜀",
    "威廉二世": "德意志帝国末代皇帝",
    "瓦特": "改良蒸汽机，推动工业革命",
    "郑成功": "开辟荆榛逐荷夷",
    "韩信": "兵仙神帅，汉初三杰",
}


def parse_embedded_json(html: str) -> tuple[dict | None, str | None]:
    m = re.search(r"window\.__EXPORT_DATA__\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
    if not m:
        m = re.search(r'const data = (\{.*?"person".*?\});\s*window\.__EXPORT_DATA__', html, re.DOTALL)
    if not m:
        return None, None
    try:
        return json.loads(m.group(1)), m.group(1)
    except json.JSONDecodeError:
        return None, None


def main():
    for name, short_review in SHORT_REVIEWS.items():
        filepath = HTML_DIR / f"{name}.html"
        if not filepath.exists():
            print(f"  [SKIP] {name}: 文件不存在")
            continue

        html = filepath.read_text(encoding="utf-8")
        data, old_json = parse_embedded_json(html)
        if data is None:
            print(f"  [SKIP] {name}: JSON 解析失败")
            continue

        person = data.get("person", {})
        old_review = person.get("shortReview", "") or person.get("short_review", "")

        if old_review and len(old_review.strip()) >= 2:
            print(f"  [SKIP] {name}: 已有 short_review: {old_review[:50]}")
            continue

        person["shortReview"] = short_review
        if "short_review" in person:
            del person["short_review"]
        data["person"] = person

        new_json = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
        new_html = html.replace(old_json, new_json, 1)
        filepath.write_text(new_html, encoding="utf-8")
        print(f"  [FIXED] {name}: short_review = '{short_review}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
