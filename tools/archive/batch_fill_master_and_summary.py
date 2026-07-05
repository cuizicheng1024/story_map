"""一键补充三国人物到 people_master.json 和 people_summary_index.json"""
import json, re, os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORY_DIR = ROOT / "storymap" / "examples" / "story"
MASTER_PATH = ROOT / "data" / "corpus" / "people_master.json"
SUMMARY_PATH = ROOT / "data" / "corpus" / "people_summary_index.json"

FIGURES = [
    "曹操", "刘备", "孙权", "关羽", "张飞", "赵云",
    "诸葛亮", "司马懿", "董卓", "马超", "夏侯惇", "张辽",
    "荀彧", "郭嘉", "孙坚", "曹丕", "曹植", "刘禅",
    "姜维", "法正", "孔融", "孟获", "蔡文姬",
]


def extract_meta_from_md(md: str, person: str) -> dict:
    """从 markdown 提取人物元信息"""
    text = md or ""
    info = {
        "person": person,
        "has_story": bool(text.strip()),
        "story_md": f"storymap/examples/story/{person}.md",
        "birth_year": None,
        "death_year": None,
        "dynasty": "",
        "birthplace": "",
        "birthplace_raw": "",
        "birthplace_modern": "",
        "foreign_name": "",
        "country": "",
        "country_zh": "",
    }
    # 出生年份
    m = re.search(r"(\d{1,4})\s*年", text[:1200])
    if m:
        try:
            y = int(m.group(1))
            if 100 < y < 500:
                info["birth_year"] = y
        except Exception:
            pass
    # 去世年份
    m2 = re.search(r"去世[\s\S]{0,30}?(\d{1,4})\s*年", text[:2000])
    if not m2:
        m2 = re.search(r"（公元?\s*(\d{1,4})\s*年\s*[—–\-]\s*(\d{1,4})\s*年）", text[:800])
        if m2:
            try:
                info["death_year"] = int(m2.group(2))
            except Exception:
                pass
    if not m2:
        # 试试 "去世**：公元XXX年"
        m2 = re.search(r"去世[\s\S]*?公元\s*(\d{1,4})\s*年", text[:2000])
    if m2 and not info.get("death_year"):
        try:
            info["death_year"] = int(m2.group(1))
        except Exception:
            pass
    # 出生地
    for pat in [
        r"出生\*\*[：:]\s*(.*?)$",
        r"出生地?[:：]\s*(.*?)$",
    ]:
        m = re.search(pat, text[:2000], re.MULTILINE)
        if m:
            raw = m.group(1).strip().rstrip("。,，;；")
            # 取"今"之前的部分
            jin = raw.find("（今")
            if jin > 0:
                info["birthplace_raw"] = raw
                info["birthplace"] = raw[:jin].strip().rstrip("（,，")
                inside = raw[jin+2:]
                end = inside.find("）")
                if end > 0:
                    info["birthplace_modern"] = inside[:end].strip()
                else:
                    info["birthplace_modern"] = inside.strip().rstrip("）")
            else:
                info["birthplace_raw"] = raw
                info["birthplace"] = raw
            break
    # 时代
    m = re.search(r"(?:时代|朝代)\*\*[：:]\s*(.*?)$", text[:1500], re.MULTILINE)
    if m:
        info["dynasty"] = m.group(1).strip()
    return info


# ====== 1. 补充 people_master.json ======
print("=== 1. people_master.json ===")

with open(MASTER_PATH, "r", encoding="utf-8") as f:
    master = json.load(f)

if not isinstance(master, dict):
    master = {"generated_at": "", "count": 0, "people": []}

people_list = list(master.get("people") or [])
existing = {p.get("person") for p in people_list if isinstance(p, dict)}

added = 0
for person in FIGURES:
    if person in existing:
        print(f"  skip {person} (already present)")
        continue
    md_path = STORY_DIR / f"{person}.md"
    if not md_path.exists():
        print(f"  SKIP {person}: no markdown")
        continue
    md_text = md_path.read_text(encoding="utf-8")
    entry = extract_meta_from_md(md_text, person)
    people_list.append(entry)
    existing.add(person)
    added += 1
    print(f"  + {person}: year={entry['birth_year']}, place={entry['birthplace'][:30] if entry['birthplace'] else '-'}, dynasty={entry['dynasty']}")

master["people"] = people_list
master["count"] = len(people_list)
master["generated_at"] = datetime.now().isoformat()

with open(MASTER_PATH, "w", encoding="utf-8") as f:
    json.dump(master, f, ensure_ascii=False, indent=2)

print(f"  Added: {added}, Total: {master['count']}\n")


# ====== 2. 补充 people_summary_index.json ======
print("=== 2. people_summary_index.json ===")

with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
    summary = json.load(f)

items = summary.get("items", {})

UPDATES = {
    "司马懿": {
        "short_review": "冢虎卧薪，终得天下。",
        "status": "曹魏权臣、军事家、西晋奠基者，以其深沉的隐忍与权谋在后世民间形成\u201c冢虎\u201d形象。",
        "identities": "军事家、政治家、谋略家、曹魏权臣、西晋奠基者",
        "achievements": "1. 辅佐曹魏三代君主，平定孟达之叛，阻诸葛亮北伐；2. 发动高平陵之变，夺取曹魏政权；3. 平定王凌之乱，为司马氏代魏奠定基础；4. 推行屯田，重视水利，保障北方经济恢复。",
        "works": [],
    },
    "诸葛亮": {
        "achievements": "1. 隆中对策，为刘备规划三分天下的战略蓝图；2. 联吴抗曹，促成赤壁之战大胜；3. 平定南中，七擒孟获稳定后方；4. 五次北伐，以攻为守巩固蜀汉国势；5. 立法施度，制定《蜀科》，整顿吏治。",
    },
    "刘禅": {
        "achievements": "1. 继承刘备即皇帝位，在位四十一年，是三国时期在位最长的君主；2. 前期信赖诸葛亮辅政，维持蜀汉稳定；3. 后期宠信宦官黄皓，导致国力衰微；4. 邓艾兵临成都时举国投降，蜀汉灭亡。",
    },
    "姜维": {
        "short_review": "继丞相之遗志，讨篡汉之逆贼。",
        "achievements": "1. 继承诸葛亮遗志，率军北伐十一次；2. 与曹魏名将邓艾、钟会长期对峙于陇西；3. 蜀汉灭亡后策动钟会谋反，图谋复国未果；4. 以'假投降'之计最后殉国，忠义传世。",
    },
    "蔡文姬": {
        "status": "东汉末年才女，文学家、音乐家、书法家，大儒蔡邕之女，以《悲愤诗》《胡笳十八拍》传世。",
    },
}

updates_applied = 0
for person, patch in UPDATES.items():
    if person in items:
        old = items[person]
        changed = []
        for k, v in patch.items():
            if old.get(k, "") != v:
                changed.append(k)
                old[k] = v
        if changed:
            updates_applied += 1
            print(f"  ✓ {person}: updated {changed}")
    else:
        print(f"  ✗ {person}: not found in summary!")

summary["items"] = items

with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\n  Updates applied: {updates_applied}")
print("Done!")
