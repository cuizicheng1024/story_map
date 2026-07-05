#!/usr/bin/env python3
"""
数据一致性验证脚本 — 检查 people_master / summary / coords / markdown / HTML 五者一致。
用法: python3 tools/validate_data.py
"""
import json, os, sys, re
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple

BASE = Path(__file__).resolve().parent.parent if '__file__' in dir() else Path(os.getcwd())
SCRIPT_DIR = BASE / 'storymap' / 'script'
sys.path.insert(0, str(SCRIPT_DIR))

# ── 加载数据 ──────────────────────────────────────────
def load_json(path: Path) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {'__error': str(e)}

CORPUS = BASE / 'data' / 'corpus'
DATA = BASE / 'data'
STORY_MD = BASE / 'storymap' / 'examples' / 'story'
ARTIFACTS = BASE / 'artifacts' / 'story_map'

pm_corpus = load_json(CORPUS / 'people_master.json')
pm_data = load_json(DATA / 'people_master.json')
psi_corpus = load_json(CORPUS / 'people_summary_index.json')
psi_data = load_json(DATA / 'people_summary_index.json')
coords_corpus = load_json(CORPUS / 'people_birth_coords_wgs84.json')
coords_data = load_json(DATA / 'people_birth_coords_wgs84.json')
hp_data = load_json(ARTIFACTS / 'stellar_home_data.json')

errors = []
warnings = []
stats = {}

# ── 1. 检查 corpus/ 和 data/ 是否同步 ──────────────────
print("=" * 60)
print("1. corpus/ ↔ data/ 同步检查")
print("=" * 60)

for name, corpus_f, data_f in [
    ('people_master.json', pm_corpus, pm_data),
    ('people_summary_index.json', psi_corpus, psi_data),
    ('people_birth_coords_wgs84.json', coords_corpus, coords_data),
]:
    c_people = len(corpus_f.get('people', corpus_f.get('items', corpus_f)))
    d_people = len(data_f.get('people', data_f.get('items', data_f)))
    if c_people != d_people:
        errors.append(f"{name}: corpus={c_people}, data={d_people} — 不同步!")
    else:
        print(f"  {name}: OK ({c_people} 条目)")

# ── 2. has_story=true 必须有 .md 文件 ───────────────────
print("\n" + "=" * 60)
print("2. has_story ↔ markdown 文件检查")
print("=" * 60)

people_list = pm_corpus.get('people', [])
has_story_people = {p['person'] for p in people_list if p.get('has_story')}
md_files = {p.stem for p in STORY_MD.glob('*.md') if p.stem and not p.stem.startswith('.')}

missing_md = has_story_people - md_files
orphan_md = md_files - has_story_people

if missing_md:
    errors.append(f"has_story=true 但缺少 .md 文件 ({len(missing_md)}): {', '.join(sorted(missing_md))}")
if orphan_md:
    warnings.append(f"有 .md 文件但 has_story≠true ({len(orphan_md)}): {', '.join(sorted(orphan_md))}")

print(f"  has_story=true: {len(has_story_people)}")
print(f"  .md 文件: {len(md_files)}")
print(f"  缺失 .md: {len(missing_md)}")
print(f"  孤立 .md: {len(orphan_md)}")

# ── 3. 有 .md 文件的人必须在 summary 里 ─────────────────
print("\n" + "=" * 60)
print("3. markdown ↔ summary/coords 注册检查")
print("=" * 60)

summary_items = psi_corpus.get('items', {})
coords_entries = {}
for k, v in coords_corpus.items():
    if isinstance(v, (list, dict)):
        coords_entries[k] = v

unregistered_md = []
no_coords_md = []
for md_path in STORY_MD.glob('*.md'):
    name = md_path.stem
    if not name or name.startswith('.'):
        continue
    if name not in summary_items:
        unregistered_md.append(name)
    if name not in coords_entries:
        no_coords_md.append(name)

if unregistered_md:
    errors.append(f"有 .md 但不在 summary 中 ({len(unregistered_md)}): {', '.join(sorted(unregistered_md))}")
print(f"  未注册到 summary: {len(unregistered_md)}")
print(f"  缺坐标: {len(no_coords_md)}")

# ── 4. .md 文件内容质量检查 ─────────────────────────────
print("\n" + "=" * 60)
print("4. Markdown 内容质量检查")
print("=" * 60)

contaminated = []
empty_md = []
for md_path in STORY_MD.glob('*.md'):
    try:
        content = md_path.read_text(encoding='utf-8')
    except Exception:
        contaminated.append((md_path.stem, '读取失败'))
        continue
    if not content.strip():
        empty_md.append(md_path.stem)
        continue
    # 检查LLM残留
    garbage_patterns = [
        r'<think[^>]*>', r'</think>',
        r'The user wants', r'I need to ', r'Let me ',
        r'I think', r'I will ', r'I should ', r'I can ',
        r'Key points', r'Wait,', r'Actually,',
        r'Let me structure',
    ]
    for pat in garbage_patterns:
        if re.search(pat, content, re.IGNORECASE):
            contaminated.append((md_path.stem, pat))
            break

if empty_md:
    errors.append(f"空 markdown 文件 ({len(empty_md)}): {', '.join(empty_md)}")
if contaminated:
    errors.append(f"LLM残留污染 ({len(contaminated)}): {', '.join(f'{n}({p})' for n,p in contaminated[:10])}")

print(f"  空文件: {len(empty_md)}")
print(f"  LLM残留: {len(contaminated)}")

# ── 5. 首页数据质量 ─────────────────────────────────────
print("\n" + "=" * 60)
print("5. 首页数据检查")
print("=" * 60)

hp_nodes = hp_data.get('nodes', [])
hp_names = {n.get('person') for n in hp_nodes if n.get('person')}
hp_has_story_names = {n['person'] for n in hp_nodes if n.get('has_story', True)}

no_quote = [n['person'] for n in hp_nodes if not n.get('quote')]
no_coords_hp = [n['person'] for n in hp_nodes if not n.get('lat') and not n.get('birth_lat')]
no_pinyin = [n['person'] for n in hp_nodes if not n.get('search_pinyin')]
no_role = [n['person'] for n in hp_nodes if not n.get('main_role_label')]

print(f"  首页节点: {len(hp_nodes)}")
print(f"  缺 quote: {len(no_quote)}")
print(f"  缺坐标: {len(no_coords_hp)}")
print(f"  缺拼音: {len(no_pinyin)}")
print(f"  缺角色: {len(no_role)}")

# 首页人名 vs has_story 人名一致性
hp_extras = hp_names - has_story_people
story_extras = has_story_people - hp_names
if hp_extras:
    warnings.append(f"首页有但has_story≠true ({len(hp_extras)}): {', '.join(sorted(hp_extras)[:10])}")
if story_extras:
    warnings.append(f"has_story=true但不在首页 ({len(story_extras)}): {', '.join(sorted(story_extras))}")

# ── 6. 人物年份合理性 ───────────────────────────────────
print("\n" + "=" * 60)
print("6. 数据合理性检查")
print("=" * 60)

weird_years = []
for p in people_list:
    name = p['person']
    birth = p.get('birth_year')
    death = p.get('death_year')
    if birth is not None and death is not None and birth > death:
        weird_years.append((name, f'出生{name}晚于卒年: {birth} > {death}'))
    if birth is not None and (birth < -3000 or birth > 2020):
        weird_years.append((name, f'出生年异常: {birth}'))

if weird_years:
    warnings.append(f"年份异常 ({len(weird_years)}):")
    for n, e in weird_years:
        print(f"    {n}: {e}")

# ── 7. 女性比例统计 ─────────────────────────────────────
print("\n" + "=" * 60)
print("7. 人口统计")
print("=" * 60)

roles = Counter(n.get('main_role_band', 'other') for n in hp_nodes)
female_kw = ['皇后','才女','美人','王妃','公主','夫人','太后','女性','女词人','女诗人','女政治家','女王']
female_count = sum(1 for name, item in summary_items.items()
                   if any(kw in (item.get('identities','') + item.get('status','')) for kw in female_kw))
foreign_count = sum(1 for n in hp_nodes if n.get('is_foreign'))

print(f"  角色分布: {dict(roles.most_common(8))}")
print(f"  女性: ~{female_count}")
print(f"  外国: {foreign_count}")

# ── 汇总 ────────────────────────────────────────────────
print("\n" + "=" * 60)
print("=== 汇总 ===")
print("=" * 60)
print(f"错误: {len(errors)}")
for e in errors:
    print(f"  ❌ {e}")
print(f"警告: {len(warnings)}")
for w in warnings:
    print(f"  ⚠️ {w}")

if not errors:
    print("\n  ✅ 所有关键检查通过!")
else:
    print(f"\n  ❌ 有 {len(errors)} 个错误需要修复")

# ── 写入报告 ────────────────────────────────────────────
report = {
    'timestamp': __import__('datetime').datetime.now().isoformat(),
    'errors': errors,
    'warnings': warnings,
    'stats': {
        'total_people_master': len(people_list),
        'has_story': len(has_story_people),
        'md_files': len(md_files),
        'homepage_nodes': len(hp_nodes),
        'missing_md': len(missing_md),
        'orphan_md': len(orphan_md),
        'contaminated_md': len(contaminated),
        'no_summary': len(unregistered_md),
        'no_coords': len(no_coords_hp),
        'no_quote': len(no_quote),
        'no_pinyin': len(no_pinyin),
    },
}
report_path = BASE / 'data' / 'reports' / 'data_validation_report.json'
report_path.parent.mkdir(parents=True, exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\n报告已写入: {report_path}")
