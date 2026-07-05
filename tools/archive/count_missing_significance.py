"""统计所有人物 Markdown 中缺失“意义”的地点数量"""
import re
from pathlib import Path
from collections import defaultdict

STORY_DIR = Path("storymap/examples/story")

total_locs = 0
missing_sig = 0
per_person = []

for md_path in sorted(STORY_DIR.glob("*.md")):
    text = md_path.read_text(encoding="utf-8")
    person = md_path.stem

    # Find location entries: **地点**：XXX followed by optional **意义**：XXX
    # Each location entry starts with "**地点**" and ends before next "**地点**" or section header
    loc_entries = re.split(r"(?=^\*\*地点\*\*)", text, flags=re.MULTILINE)
    loc_entries = [e for e in loc_entries if re.match(r"^\*\*地点\*\*", e)]

    for entry in loc_entries:
        total_locs += 1
        has_sig = bool(re.search(r"^\*\*意义\*\*[：:]\s*\S", entry, re.MULTILINE))
        if not has_sig:
            missing_sig += 1

    if loc_entries:
        missing_count = sum(
            1 for e in loc_entries
            if not re.search(r"^\*\*意义\*\*[：:]\s*\S", e, re.MULTILINE)
        )
        per_person.append((person, len(loc_entries), missing_count))

print(f"总地点数: {total_locs}")
print(f"缺少意义: {missing_sig}")
print(f"覆盖率: {(total_locs - missing_sig) / total_locs * 100:.1f}%")
print()

# Group by missing count
for p, total, missing in sorted(per_person, key=lambda x: -x[2])[:30]:
    if missing > 0:
        print(f"  {p}: {total} locs, {missing} missing")
