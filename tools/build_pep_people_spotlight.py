"""兼容入口：PEP 人物 spotlight 索引构建。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from tools.build.build_people_summary_index import (  # noqa: F401
    _person_sort_key,
    _summarize,
    pinyin_variants,
    story_person_names,
)

SUMMARY_INDEX_FILENAME = "people_summary_index.json"


def main() -> int:
    file_path = Path(__file__).resolve()
    repo_root = file_path.parents[1]
    story_dir = repo_root / "storymap" / "examples" / "story"
    out: Dict[str, Any] = {}
    for name in sorted(story_person_names(story_dir), key=_person_sort_key):
        path = story_dir / f"{name}.md"
        if not path.is_file():
            continue
        md = path.read_text(encoding="utf-8", errors="ignore")
        out[name] = _summarize(name, md)

    payload = {"items": out, "meta": {"count": len(out)}}
    output_path = repo_root / "data" / SUMMARY_INDEX_FILENAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
