"""
把 relations_export.json 的改动同步回 SQLite。
用法: python3 tools/sync_relations_from_json.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = PROJECT_ROOT / "data" / "relations_export.json"
DB_PATH = PROJECT_ROOT / "data" / "people_knowledge.db"


def main() -> int:
    if not JSON_PATH.exists():
        print(f"ERROR: {JSON_PATH} not found", file=sys.stderr)
        return 1

    import sqlite3
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    relations = data.get("relations", [])
    if not isinstance(relations, list):
        print("ERROR: invalid JSON format", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # 收集 JSON 中的所有关系对
    json_pairs = set()
    for r in relations:
        a = str(r.get("source") or "").strip()
        b = str(r.get("target") or "").strip()
        if not a or not b or a == b:
            continue
        if a > b:
            a, b = b, a
        json_pairs.add((a, b))

    # 删掉 DB 中有但 JSON 中没有的关系
    db_rows = conn.execute(
        "SELECT source_person, target_person FROM relationships"
    ).fetchall()
    removed = 0
    for src, tgt in db_rows:
        pair = (src, tgt) if src <= tgt else (tgt, src)
        if pair not in json_pairs:
            conn.execute(
                "DELETE FROM relationships WHERE source_person = ? AND target_person = ?",
                (src, tgt),
            )
            removed += 1
    if removed:
        print(f"Removed {removed} relations not in JSON")

    # 插入/更新 JSON 中的关系
    upserted = 0
    for r in relations:
        a = str(r.get("source") or "").strip()
        b = str(r.get("target") or "").strip()
        if not a or not b or a == b:
            continue
        if a > b:
            a, b = b, a
        label = str(r.get("relationship") or "相关人物").strip()
        weight = int(r.get("weight") or 2)
        rtype = str(r.get("origin") or "manual").strip()
        evidence = str(r.get("evidence") or "").strip()

        conn.execute(
            """
            INSERT INTO relationships (source_person, target_person, origin, relationship, weight, evidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_person, target_person) DO UPDATE SET
                origin = excluded.origin,
                relationship = excluded.relationship,
                weight = excluded.weight,
                evidence = excluded.evidence,
                updated_at = datetime('now')
            """,
            (a, b, rtype, label, weight, evidence),
        )
        upserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    conn.close()

    print(f"Upserted {upserted} relations")
    print(f"Total in DB: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
