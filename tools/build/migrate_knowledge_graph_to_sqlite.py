"""
将 stellar_home_data.json 和 people_knowledge_graph.json 迁移到 SQLite。
运行一次即可：python tools/migrate_knowledge_graph_to_sqlite.py
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STELLAR_HOME = PROJECT_ROOT / "artifacts" / "story_map" / "stellar_home_data.json"
KNOWLEDGE_GRAPH = PROJECT_ROOT / "data" / "corpus" / "people_knowledge_graph.json"
DB_PATH = PROJECT_ROOT / "data" / "people_knowledge.db"


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS people (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            file        TEXT    NOT NULL,
            dynasty     TEXT    NOT NULL DEFAULT '',
            birth_year  INTEGER,
            death_year  INTEGER,
            time_year   INTEGER,
            quote       TEXT    NOT NULL DEFAULT '',
            review      TEXT    NOT NULL DEFAULT '',
            aliases     TEXT    NOT NULL DEFAULT '[]',
            foreign_name TEXT   NOT NULL DEFAULT '',
            domain_tags TEXT    NOT NULL DEFAULT '[]',
            main_role_band TEXT NOT NULL DEFAULT '',
            main_role_label TEXT NOT NULL DEFAULT '',
            birthplace  TEXT    NOT NULL DEFAULT '',
            birthplace_raw TEXT  NOT NULL DEFAULT '',
            birthplace_modern TEXT NOT NULL DEFAULT '',
            birth_lat_wgs84 REAL,
            birth_lng_wgs84 REAL,
            birth_lat    REAL,
            birth_lng    REAL,
            birth_coord_system TEXT NOT NULL DEFAULT '',
            has_story    INTEGER NOT NULL DEFAULT 1,
            native_place TEXT    NOT NULL DEFAULT '',
            native_place_raw TEXT NOT NULL DEFAULT '',
            native_place_modern TEXT NOT NULL DEFAULT '',
            search_keys  TEXT    NOT NULL DEFAULT '[]',
            search_tokens TEXT   NOT NULL DEFAULT '[]',
            search_pinyin TEXT   NOT NULL DEFAULT '[]',
            is_foreign   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_person   TEXT NOT NULL,
            target_person   TEXT NOT NULL,
            origin          TEXT NOT NULL DEFAULT 'manual',
            relationship    TEXT NOT NULL DEFAULT '相关人物',
            weight          INTEGER NOT NULL DEFAULT 1,
            confidence      REAL,
            evidence        TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_person, target_person)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_relationships_source
            ON relationships(source_person)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_relationships_target
            ON relationships(target_person)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_people_dynasty
            ON people(dynasty)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_people_has_story
            ON people(has_story)
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS people_fts USING fts5(
            name,
            aliases,
            foreign_name,
            birthplace,
            dynasty,
            content='people',
            content_rowid='id'
        )
    """)

    conn.commit()
    print("[schema] tables created")


def migrate_people(conn: sqlite3.Connection) -> int:
    if not STELLAR_HOME.exists():
        print(f"[migrate] ERROR: {STELLAR_HOME} not found", file=sys.stderr)
        return 0

    data = json.loads(STELLAR_HOME.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        return 0

    count = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("person") or "").strip()
        if not name:
            continue

        conn.execute(
            """
            INSERT OR REPLACE INTO people (
                name, file, dynasty, birth_year, death_year, time_year,
                quote, review, aliases, foreign_name, domain_tags,
                main_role_band, main_role_label,
                birthplace, birthplace_raw, birthplace_modern,
                birth_lat_wgs84, birth_lng_wgs84, birth_lat, birth_lng, birth_coord_system,
                has_story, native_place, native_place_raw, native_place_modern,
                search_keys, search_tokens, search_pinyin, is_foreign,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                name,
                str(node.get("file") or f"{name}.html").strip(),
                str(node.get("dynasty") or "").strip(),
                _coerce_int(node.get("birth_year")),
                _coerce_int(node.get("death_year")),
                _coerce_int(node.get("time_year")),
                str(node.get("quote") or "").strip(),
                str(node.get("review") or "").strip(),
                json.dumps(_string_list(node.get("aliases")), ensure_ascii=False),
                str(node.get("foreign_name") or "").strip(),
                json.dumps(_string_list(node.get("domain_tags")), ensure_ascii=False),
                str(node.get("main_role_band") or "").strip(),
                str(node.get("main_role_label") or "").strip(),
                str(node.get("birthplace") or "").strip(),
                str(node.get("birthplace_raw") or "").strip(),
                str(node.get("birthplace_modern") or "").strip(),
                _coerce_float(node.get("birth_lat_wgs84")),
                _coerce_float(node.get("birth_lng_wgs84")),
                _coerce_float(node.get("birth_lat")),
                _coerce_float(node.get("birth_lng")),
                str(node.get("birth_coord_system") or "").strip(),
                1 if node.get("has_story", True) else 0,
                str(node.get("native_place") or "").strip(),
                str(node.get("native_place_raw") or "").strip(),
                str(node.get("native_place_modern") or "").strip(),
                json.dumps(_string_list(node.get("search_keys")), ensure_ascii=False),
                json.dumps(_string_list(node.get("search_tokens")), ensure_ascii=False),
                json.dumps(_string_list(node.get("search_pinyin")), ensure_ascii=False),
                1 if node.get("is_foreign") else 0,
            ),
        )
        count += 1

    conn.commit()
    print(f"[migrate] {count} people inserted")
    return count


def migrate_edges(conn: sqlite3.Connection) -> int:
    """从 stellar_home_data.json 的 edges 和 people_knowledge_graph.json 迁移关系"""
    edge_count = 0

    # 先收集 KG 中有但 people 表中没有的名字
    missing_names: set[str] = set()
    if KNOWLEDGE_GRAPH.exists():
        kg = json.loads(KNOWLEDGE_GRAPH.read_text(encoding="utf-8"))
        kg_nodes = kg.get("nodes", [])
        if isinstance(kg_nodes, list):
            for n in kg_nodes:
                if isinstance(n, dict):
                    name = str(n.get("id") or n.get("label") or "").strip()
                    if name:
                        missing_names.add(name)

    existing = set()
    for row in conn.execute("SELECT name FROM people"):
        existing.add(row[0])
    missing_names -= existing

    for name in sorted(missing_names):
        conn.execute(
            "INSERT OR IGNORE INTO people (name, file, has_story) VALUES (?, ?, 0)",
            (name, f"{name}.html"),
        )
    if missing_names:
        conn.commit()
        print(f"[migrate] added {len(missing_names)} KG-only people (has_story=0)")
    edge_count += len(missing_names)

    # 1. 从 stellar_home_data.json 读取 edges（按索引的边）
    if STELLAR_HOME.exists():
        data = json.loads(STELLAR_HOME.read_text(encoding="utf-8"))
        nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
        edges = data.get("edges", [])
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                try:
                    a = int(edge.get("a"))
                    b = int(edge.get("b"))
                except Exception:
                    continue
                if a < 0 or b < 0 or a == b:
                    continue
                if a >= len(nodes) or b >= len(nodes):
                    continue
                source = str(nodes[a].get("person") or "").strip()
                target = str(nodes[b].get("person") or "").strip()
                if not source or not target or source == target:
                    continue
                rtype = str(edge.get("type") or "graph").strip()
                rel = str(edge.get("label") or "相关人物").strip()
                try:
                    weight = int(edge.get("weight") or 0)
                except Exception:
                    weight = 0
                try:
                    confidence = float(edge.get("confidence"))
                except Exception:
                    confidence = None
                evidence = str(edge.get("evidence") or "").strip()
                if rtype == "same_book":
                    continue  # 自动生成的不导入
                _upsert_relation(conn, source, target, rtype, rel, weight, confidence, evidence)
                edge_count += 1

    # 2. 从 people_knowledge_graph.json 读取人工标注边
    if KNOWLEDGE_GRAPH.exists():
        kg = json.loads(KNOWLEDGE_GRAPH.read_text(encoding="utf-8"))
        kg_edges = kg.get("edges", [])
        if isinstance(kg_edges, list):
            for edge in kg_edges:
                if not isinstance(edge, dict):
                    continue
                source = str(edge.get("source") or "").strip()
                target = str(edge.get("target") or "").strip()
                if not source or not target or source == target:
                    continue
                rtype = str(edge.get("type") or "manual").strip()
                rel = str(edge.get("label") or "相关人物").strip()
                try:
                    weight = int(edge.get("weight") or 0)
                except Exception:
                    weight = 0
                evidence = str(edge.get("evidence") or "").strip()
                _upsert_relation(conn, source, target, rtype, rel, weight, None, evidence)

    conn.commit()
    print(f"[migrate] {edge_count} non-same_book edges from stellar_home_data")
    total = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()
    print(f"[migrate] total relations in DB: {total[0] if total else 0}")
    return edge_count


def _upsert_relation(conn, source, target, rtype, rel, weight, confidence, evidence):
    """插入或更新关系边"""
    # 确保 source ≤ target 以保持一致性
    if source > target:
        source, target = target, source
    conn.execute(
        """
        INSERT INTO relationships (source_person, target_person, origin, relationship, weight, confidence, evidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_person, target_person) DO UPDATE SET
            origin = excluded.origin,
            relationship = excluded.relationship,
            weight = excluded.weight,
            confidence = excluded.confidence,
            evidence = excluded.evidence,
            updated_at = datetime('now')
        """,
        (source, target, rtype, rel, weight, confidence, evidence),
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO people_fts(people_fts) VALUES('rebuild')")
    conn.commit()
    print("[fts] rebuilt")


def _coerce_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _coerce_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _string_list(items):
    if not isinstance(items, list):
        return []
    return [str(x).strip() for x in items if str(x).strip()]


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    create_schema(conn)
    n_people = migrate_people(conn)
    n_edges = migrate_edges(conn)
    rebuild_fts(conn)

    conn.close()
    print(f"\n✓ SQLite DB ready: {DB_PATH}")
    print(f"  people: {n_people}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
