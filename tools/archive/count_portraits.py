import json, re
from pathlib import Path

with open('data/corpus/people_summary_index.json') as f:
    psi = json.load(f)
all_people = set(psi['items'].keys())

portraits_dir = Path('artifacts/story_map/portraits')
portrait_names = set()
for f in portraits_dir.glob('*'):
    m = re.match(r'^(.+?)-[a-f0-9]{8,}\.(jpg|png|svg|webp)', f.name)
    if m:
        name = m.group(1).replace('_', ' ')
        portrait_names.add(name)

has_portrait = set()
for p in all_people:
    safe = p.replace(' ', '_')
    if p in portrait_names:
        has_portrait.add(p)
    else:
        found = list(portraits_dir.glob(f'{safe}-*'))
        if found:
            has_portrait.add(p)

missing = all_people - has_portrait
print(f'Total: {len(all_people)}')
print(f'Has portrait: {len(has_portrait)}')
print(f'Missing: {len(missing)}')
print()
print('Sample has:')
for p in sorted(has_portrait)[:10]:
    print(f'  ✓ {p}')
print()
print('Sample missing:')
for p in sorted(missing)[:30]:
    print(f'  ✗ {p}')
