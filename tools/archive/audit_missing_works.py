"""盘点缺失作品摘要的人物和作品"""
import json
from collections import defaultdict

with open('data/corpus/people_summary_index.json', encoding='utf-8') as f:
    psi = json.load(f)
items = psi.get('items', {})

with open('data/corpus/work_summary_llm.json', encoding='utf-8') as f:
    ws = json.load(f)

works_to_people = defaultdict(list)
for p, info in items.items():
    for w in info.get('works', []):
        works_to_people[w].append(p)

missing = {w: people for w, people in works_to_people.items() if w not in ws}
existing = {w: people for w, people in works_to_people.items() if w in ws}

print(f"总作品: {len(works_to_people)}, 有摘要: {len(existing)}, 缺失: {len(missing)}")
print()

people_missing = defaultdict(list)
for w, people in missing.items():
    for p in people:
        people_missing[p].append(w)

for p in sorted(people_missing.keys()):
    works = people_missing[p]
    print(f"{p} ({len(works)}):")
    for w in works:
        print(f"    - {w}")
