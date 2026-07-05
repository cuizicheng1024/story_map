import re
from pathlib import Path

story = Path("storymap/examples/story")

generic_re = re.compile(
    r"是理解.*重要地点|重要的人生节点|紧密相关.*是理解|是.*人生.*重要|"
    r"紧密相关.*生平|这一事件.*重要|是.*生平中.*重要"
)

total_sigs = 0
generic_sigs = 0
problem_people = []

for md in sorted(story.glob("*.md")):
    text = md.read_text(encoding="utf-8")
    sigs = re.findall(r"[-*]\s*\*\*意义\*\*[：:]\s*(.+)", text)
    bad = 0
    for s in sigs:
        total_sigs += 1
        if len(s.strip()) < 20:
            bad += 1
            generic_sigs += 1
        elif generic_re.search(s):
            bad += 1
            generic_sigs += 1
    if bad > 0:
        problem_people.append((md.stem, bad, len(sigs)))

print(f"总意义条数: {total_sigs}")
print(f"套话或过短: {generic_sigs}")
print(f"有问题的人物: {len(problem_people)}")
for p, bad, total in problem_people[:30]:
    print(f"  {p}: {bad}/{total}")
