# rename xiaoming to huang xiaoming
import json, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = "晓明", "黄晓明"

# 1. people_summary_index.json
p = ROOT / "data/corpus/people_summary_index.json"
d = json.loads(p.read_text("utf-8"))
if OLD in d.get("items", {}):
    d["items"][NEW] = d["items"].pop(OLD)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    print("1. people_summary_index.json ✓")

# 2. people_master.json
p = ROOT / "data/corpus/people_master.json"
d = json.loads(p.read_text("utf-8"))
if isinstance(d, dict) and "people" in d:
    for e in d["people"]:
        if e.get("person") == OLD:
            e["person"] = NEW
            print("2. people_master.json ✓")

# Also check top-level keys
if isinstance(d, dict) and OLD in d:
    d[NEW] = d.pop(OLD)
    print("2b. people_master (top-level) ✓")
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")

# 3. SQLite
db = sqlite3.connect(str(ROOT / "data/people_knowledge.db"))
for col in ("source_person", "target_person"):
    db.execute(f"UPDATE relationships SET {col} = ? WHERE {col} = ?", (NEW, OLD))
db.commit()
db.close()
print("3. people_knowledge.db ✓")

# 4. work_summary_index.json
p = ROOT / "data/corpus/work_summary_index.json"
d = json.loads(p.read_text("utf-8"))
mod = 0
for k, v in d.items():
    if OLD in v.get("authors", []):
        v["authors"] = [NEW if a == OLD else a for a in v["authors"]]
        mod += 1
if mod:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    print(f"4. work_summary_index.json ✓ ({mod} entries)")

# 5. people_knowledge_graph.json
p = ROOT / "data/corpus/people_knowledge_graph.json"
d = json.loads(p.read_text("utf-8"))
if OLD in d:
    d[NEW] = d.pop(OLD)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    print("5. people_knowledge_graph.json ✓")

# 6. people_birth_coords_wgs84.json
p = ROOT / "data/corpus/people_birth_coords_wgs84.json"
if p.exists():
    d = json.loads(p.read_text("utf-8"))
    if OLD in d:
        d[NEW] = d.pop(OLD)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
        print("6. people_birth_coords_wgs84.json ✓")

# 7. people_master_pep.json
p = ROOT / "data/corpus/people_master_pep.json"
if p.exists():
    d = json.loads(p.read_text("utf-8"))
    if isinstance(d, dict) and OLD in d:
        d[NEW] = d.pop(OLD)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
        print("7. people_master_pep.json ✓")

print("\nDone!")
