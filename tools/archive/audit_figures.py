"""审计三国人物数据完整性"""
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ['曹操','刘备','孙权','关羽','张飞','赵云','诸葛亮','司马懿','董卓',
           '马超','夏侯惇','张辽','荀彧','郭嘉','孙坚','曹丕','曹植','刘禅',
           '姜维','法正','孔融','孟获','蔡文姬']

# 1. Markdown
print('=== 1. Markdown 文件 ===')
for p in FIGURES:
    md = ROOT / 'storymap' / 'examples' / 'story' / f'{p}.md'
    e = md.exists()
    s = md.stat().st_size if e else 0
    print(f'  {p:8s} {"✓" if e else "✗"} {s}B')

# 2. people_summary_index
print('\n=== 2. people_summary_index.json ===')
with open(ROOT / 'data' / 'corpus' / 'people_summary_index.json', encoding='utf-8') as f:
    psi = json.load(f)
items = psi.get('items', {})

IMPORTANT = ['spotlight','intro','short_review','status','identities','achievements','works']
for p in FIGURES:
    item = items.get(p, {})
    missing = [k for k in IMPORTANT if not item.get(k) or item.get(k) == '']
    e = p in items
    print(f'  {p:8s} {"✓" if e else "✗"} missing: {missing if missing else "none"}')

# 3. HTML
print('\n=== 3. HTML 产物 ===')
for p in FIGURES:
    html = ROOT / 'artifacts' / 'story_map' / f'{p}.html'
    e = html.exists()
    s = html.stat().st_size if e else 0
    print(f'  {p:8s} {"✓" if e else "✗"} {s}B')

# 4. people_master
print('\n=== 4. people_master.json ===')
master_path = ROOT / 'data' / 'corpus' / 'people_master.json'
if master_path.exists():
    with open(master_path, encoding='utf-8') as f:
        pm = json.load(f)
    for p in FIGURES:
        e = p in pm
        print(f'  {p:8s} {"✓" if e else "✗"}')
else:
    print('  file not found')

# 5. birth_coords
print('\n=== 5. birth_coords.json ===')
bc_path = ROOT / 'data' / 'corpus' / 'birth_coords.json'
if bc_path.exists():
    with open(bc_path, encoding='utf-8') as f:
        bc = json.load(f)
    for p in FIGURES:
        e = p in bc
        print(f'  {p:8s} {"✓" if e else "✗"}')
else:
    print('  file not found')
