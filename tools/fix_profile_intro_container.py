#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [
    REPO_ROOT / "storymap" / "examples" / "story_map",
    REPO_ROOT / "artifacts" / "story_map",
]

PATTERN = re.compile(
    r'(?s)<div className="mt-4 rounded-2xl border border-\[#c8b496\]/45 bg-gradient-to-br from-amber-50/90 to-white/85 px-4 md:px-5 py-4 text-left shadow-sm">\n'
    r'\s{14}<div className="space-y-3">\n'
    r'(?P<body>.*?)'
    r'\s{14}</div>\n'
    r'\s{12}</div>\n'
)


def rewrite_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")

    def _replace(match: re.Match[str]) -> str:
        body = match.group("body")
        return (
            '            <div className="mt-4 space-y-3 text-left">\n'
            f"{body}"
            '            </div>\n'
        )

    updated, count = PATTERN.subn(_replace, text, count=1)
    if count == 0:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    changed = []
    for directory in TARGET_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.html")):
            if rewrite_file(path):
                changed.append(path)
    print(f"changed={len(changed)}")
    for path in changed[:10]:
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
