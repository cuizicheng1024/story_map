"""
关系图谱管理工具 — SQLite 维护脚本。

用法：
    # 列出某人所有关系
    python tools/manage_relations.py show 李白

    # 搜索人物
    python tools/manage_relations.py search 李

    # 添加关系
    python tools/manage_relations.py add 李白 杜甫 \
        --origin manual --relationship 好友 --weight 5 --evidence "李杜齐名"

    # 删除关系
    python tools/manage_relations.py remove 李白 杜甫

    # 更新关系标签/权重
    python tools/manage_relations.py update 李白 杜甫 \
        --relationship 诗友 --weight 4

    # 列出所有关系
    python tools/manage_relations.py list [--limit 100]

    # 检查某人缺少哪些关系（对比 Markdown）
    python tools/manage_relations.py suggest 李白

    # 重建 FTS 全文索引
    python tools/manage_relations.py rebuild-fts
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "people_knowledge.db"

ORIGINS = ["manual", "bio"]


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run migrate_knowledge_graph_to_sqlite.py first.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    name = args.person.strip()
    rows = conn.execute(
        """
        SELECT * FROM relationships
        WHERE source_person = ? OR target_person = ?
        ORDER BY weight DESC, confidence DESC
        LIMIT ?
        """,
        (name, name, args.limit),
    ).fetchall()

    if not rows:
        print(f"'{name}' 当前没有维护的关系。")
        return

    print(f"\n{'─'*70}")
    print(f"  {name} 的关系图谱（共 {len(rows)} 条）")
    print(f"{'─'*70}")
    for r in rows:
        other = r["target_person"] if r["source_person"] == name else r["source_person"]
        print(f"  {other:12s}  │  {r['relationship']:8s}  │  weight={r['weight']}  │  {r['evidence'] or '(无证据)'}")
    print(f"{'─'*70}\n")


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    src, tgt = args.source.strip(), args.target.strip()
    if src == tgt:
        print("ERROR: source and target cannot be the same", file=sys.stderr)
        return
    if src > tgt:
        src, tgt = tgt, src

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
        (src, tgt, args.origin, args.relationship, args.weight, args.evidence),
    )
    conn.commit()
    print(f"✓ 已添加/更新关系: {src} ← {args.relationship} → {tgt}")


def cmd_remove(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    src, tgt = args.source.strip(), args.target.strip()
    if src > tgt:
        src, tgt = tgt, src
    conn.execute(
        "DELETE FROM relationships WHERE source_person = ? AND target_person = ?",
        (src, tgt),
    )
    conn.commit()
    print(f"✓ 已删除关系: {src} ↔ {tgt}")


def cmd_update(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    src, tgt = args.source.strip(), args.target.strip()
    if src > tgt:
        src, tgt = tgt, src

    sets = []
    params = []
    if args.relationship is not None:
        sets.append("relationship = ?")
        params.append(args.relationship)
    if args.weight is not None:
        sets.append("weight = ?")
        params.append(args.weight)
    if args.evidence is not None:
        sets.append("evidence = ?")
        params.append(args.evidence)
    if args.origin is not None:
        sets.append("origin = ?")
        params.append(args.origin)

    if not sets:
        print("ERROR: at least one of --relationship, --weight, --evidence, --origin required", file=sys.stderr)
        return

    sets.append("updated_at = datetime('now')")
    params.extend([src, tgt])

    conn.execute(
        f"UPDATE relationships SET {', '.join(sets)} WHERE source_person = ? AND target_person = ?",
        params,
    )
    conn.commit()
    print(f"✓ 已更新关系: {src} ↔ {tgt}")


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    rows = conn.execute(
        "SELECT * FROM relationships ORDER BY weight DESC, source_person LIMIT ?",
        (args.limit,),
    ).fetchall()
    print(f"\n{'─'*70}")
    print(f"  全部关系（共 {len(rows)} 条）")
    print(f"{'─'*70}")
    for r in rows:
        print(f"  {r['source_person']:12s}  ← {r['relationship']:10s} →  {r['target_person']:12s}  w={r['weight']}")
    print(f"{'─'*70}\n")


def cmd_search(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    query = args.query.strip()
    rows = conn.execute(
        "SELECT name, dynasty, birthplace FROM people WHERE name LIKE ? OR aliases LIKE ? LIMIT 20",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    if not rows:
        print(f"未找到匹配 '{query}' 的人物。")
        return
    for r in rows:
        print(f"  {r['name']:12s}  {r['dynasty']:16s}  {r['birthplace']}")


def cmd_stats(conn: sqlite3.Connection, _args: argparse.Namespace) -> None:
    n_people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    n_story = conn.execute("SELECT COUNT(*) FROM people WHERE has_story = 1").fetchone()[0]
    n_rels = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    top = conn.execute(
        """
        SELECT source_person, target_person, weight, relationship
        FROM relationships ORDER BY weight DESC LIMIT 10
        """
    ).fetchall()
    print(f"\n  人物: {n_people} (有故事: {n_story})")
    print(f"  关系: {n_rels}")
    print(f"  Top 10 权重:")
    for r in top:
        print(f"    {r['source_person']:12s} ← {r['relationship']:8s} → {r['target_person']:12s}  w={r['weight']}")
    print()


def cmd_rebuild_fts(conn: sqlite3.Connection, _args: argparse.Namespace) -> None:
    conn.execute("INSERT INTO people_fts(people_fts) VALUES('rebuild')")
    conn.commit()
    print("✓ FTS 全文索引已重建")


def cmd_count(conn: sqlite3.Connection, _args: argparse.Namespace) -> None:
    n = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    print(n)


def cmd_dump(conn: sqlite3.Connection, _args: argparse.Namespace) -> None:
    """以 JSON 格式导出所有关系。"""
    people_rows = conn.execute("SELECT name, dynasty, birth_year, death_year FROM people WHERE has_story = 1").fetchall()
    rel_rows = conn.execute("SELECT * FROM relationships ORDER BY weight DESC").fetchall()
    output = {
        "people": [{"name": r["name"], "dynasty": r["dynasty"], "birth_year": r["birth_year"], "death_year": r["death_year"]} for r in people_rows],
        "relationships": [dict(r) for r in rel_rows],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="关系图谱管理工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="查看某人的关系")
    p_show.add_argument("person")
    p_show.add_argument("--limit", type=int, default=30)

    p_search = sub.add_parser("search", help="搜索人物")
    p_search.add_argument("query")

    p_list = sub.add_parser("list", help="列出所有关系")
    p_list.add_argument("--limit", type=int, default=100)

    p_add = sub.add_parser("add", help="添加关系")
    p_add.add_argument("source")
    p_add.add_argument("target")
    p_add.add_argument("--origin", default="manual", choices=ORIGINS)
    p_add.add_argument("--relationship", default="相关人物")
    p_add.add_argument("--weight", type=int, default=3)
    p_add.add_argument("--evidence", default="")

    p_remove = sub.add_parser("remove", help="删除关系")
    p_remove.add_argument("source")
    p_remove.add_argument("target")

    p_update = sub.add_parser("update", help="更新关系")
    p_update.add_argument("source")
    p_update.add_argument("target")
    p_update.add_argument("--origin", choices=ORIGINS)
    p_update.add_argument("--relationship")
    p_update.add_argument("--weight", type=int)
    p_update.add_argument("--evidence")

    sub.add_parser("stats", help="统计信息")
    sub.add_parser("rebuild-fts", help="重建全文索引")
    sub.add_parser("count", help="输出关系总数")
    sub.add_parser("dump", help="导出 JSON")

    args = parser.parse_args()

    if args.command in ("count", "dump"):
        print = sys.stdout.write  # suppress extra output for scripts

    conn = _connect()
    try:
        {
            "show": cmd_show,
            "search": cmd_search,
            "list": cmd_list,
            "add": cmd_add,
            "remove": cmd_remove,
            "update": cmd_update,
            "stats": cmd_stats,
            "rebuild-fts": cmd_rebuild_fts,
            "count": cmd_count,
            "dump": cmd_dump,
        }[args.command](conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
