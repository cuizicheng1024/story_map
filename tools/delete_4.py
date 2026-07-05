import json, sqlite3
from pathlib import Path

DELETE = ['姚文元', '张春桥', '王洪文', '任世江']

# 1. people_summary_index.json
p = Path('data/corpus/people_summary_index.json')
d = json.loads(p.read_text('utf-8'))
items = d.get('items', {})
for name in DELETE:
    items.pop(name, None)
d['meta']['count'] = len(items)
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')
print(f'1. summary_index: {len(items)}')

# 2. people_master.json
p = Path('data/corpus/people_master.json')
d = json.loads(p.read_text('utf-8'))
if isinstance(d, dict) and 'people' in d:
    d['people'] = [e for e in d['people'] if e.get('person') not in DELETE]
    d['count'] = len(d['people'])
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')
    print(f'2. people_master: {d["count"]}')

# 3. people_knowledge.db
db = sqlite3.connect('data/people_knowledge.db')
for name in DELETE:
    db.execute('DELETE FROM relationships WHERE source_person=? OR target_person=?', (name, name))
db.commit()
db.close()
print('3. db cleaned')

# 4. birth_coords
p = Path('data/corpus/people_birth_coords_wgs84.json')
if p.exists():
    d = json.loads(p.read_text('utf-8'))
    for name in DELETE:
        d.pop(name, None)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')
    print('4. birth_coords cleaned')

# 5. Markdown + HTML
for name in DELETE:
    md = Path('storymap/examples/story') / f'{name}.md'
    if md.exists():
        md.unlink()
        print(f'5. deleted md: {name}')
    html = Path('artifacts/story_map') / f'{name}.html'
    if html.exists():
        html.unlink()
        print(f'6. deleted html: {name}')

print(f'Done: deleted {DELETE}')
