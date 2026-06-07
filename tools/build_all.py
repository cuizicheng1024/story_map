#!/usr/bin/env python3
"""build_all.py - 数据单源构建入口

职责：
  1. 重新生成 data/people_master.json（教材总索引）
  2. 重新生成 data/people_master_pep.json（PEP 教材人物）
  3. 增量重渲染 storymap/examples/story_map/*.html（人物页）
  4. 重新生成 data/people_birth_coords_wgs84.json（出生地经纬度）
  5. 重新生成 storymap/examples/story_map/stellar_home_data.json + index.html

数据源：单一来源 = storymap/examples/story/*.md
幂等：默认不会触发 LLM 补缺、不会重新 geocode。带 --refresh-geocode 时重新跑一次地理编码。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STORY_DIR = REPO_ROOT / "storymap" / "examples" / "story"
STORY_MAP_DIR = REPO_ROOT / "storymap" / "examples" / "story_map"
DATA_DIR = REPO_ROOT / "data"
HOME_DATA = STORY_MAP_DIR / "stellar_home_data.json"
MANIFEST_JSON = DATA_DIR / "build_manifest.json"
VALIDATION_JSON = DATA_DIR / "build_validation_report.json"
BAD_PERSON_NAMES = {"人物", "母亲", "刘某", "人物 生平传记与足迹"}


def _print_section(title: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}\n  {title}\n{bar}", flush=True)


def _run(cmd: list[str], cwd: str | None = None) -> int:
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=cwd or str(REPO_ROOT))


def _story_files() -> list[Path]:
    if not STORY_DIR.exists():
        return []
    return sorted(STORY_DIR.glob("*.md"))


def _story_people() -> list[str]:
    out: list[str] = []
    for p in _story_files():
        name = p.stem.strip()
        if not name or name in BAD_PERSON_NAMES:
            continue
        out.append(name)
    return sorted(set(out))


def _existing_htmls() -> set[str]:
    if not STORY_MAP_DIR.exists():
        return set()
    return {p.stem for p in STORY_MAP_DIR.glob("*.html")}


def _canonical_html_people() -> list[str]:
    out: list[str] = []
    if not STORY_MAP_DIR.exists():
        return out
    for p in STORY_MAP_DIR.glob("*.html"):
        if not p.is_file() or p.name == "index.html":
            continue
        stem = p.stem.strip()
        if not stem or "__pure__" in stem or stem in BAD_PERSON_NAMES:
            continue
        out.append(stem)
    return sorted(set(out))


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime": round(stat.st_mtime, 3),
        "sha1": _sha1_file(path)[:12],
        "path": str(path.relative_to(REPO_ROOT)),
    }


def _load_people_index(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        obj = _read_json(path)
    except Exception:
        return {}
    items = obj.get(key, []) if isinstance(obj, dict) else []
    out: dict[str, dict] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("person", "")).strip()
        if not name:
            continue
        out[name] = item
    return out


def _load_coords_index(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    try:
        obj = _read_json(path)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, list[float]] = {}
    for k, v in obj.items():
        name = str(k or "").strip()
        if not name:
            continue
        if isinstance(v, list) and len(v) >= 2:
            out[name] = v
    return out


def _has_home_coords(node: dict) -> bool:
    try:
        lat = node.get("birth_lat_wgs84")
        lng = node.get("birth_lng_wgs84")
        return isinstance(lat, (int, float)) and isinstance(lng, (int, float))
    except Exception:
        return False


def _issue(code: str, items: list[str], level: str, message: str, limit: int = 20) -> dict | None:
    if not items:
        return None
    return {
        "code": code,
        "level": level,
        "message": message,
        "count": len(items),
        "samples": items[:limit],
    }


def _build_manifest() -> dict:
    story_people = _story_people()
    html_people = _canonical_html_people()
    master = _load_people_index(DATA_DIR / "people_master.json", "people")
    pep = _load_people_index(DATA_DIR / "people_master_pep.json", "people")
    home = _load_people_index(HOME_DATA, "nodes")
    coords = _load_coords_index(DATA_DIR / "people_birth_coords_wgs84.json")
    people_union = sorted(set(story_people) | set(html_people) | set(master.keys()) | set(home.keys()) | set(coords.keys()))

    people_rows = []
    for name in people_union:
        md_path = STORY_DIR / f"{name}.md"
        html_path = STORY_MAP_DIR / f"{name}.html"
        master_item = master.get(name) or {}
        home_item = home.get(name) or {}
        people_rows.append(
            {
                "person": name,
                "md_exists": md_path.exists(),
                "html_exists": html_path.exists(),
                "in_master": name in master,
                "in_pep": name in pep,
                "in_home": name in home,
                "in_coords": name in coords,
                "master_has_story": master_item.get("has_story"),
                "master_story_md": master_item.get("story_md"),
                "home_has_story": home_item.get("has_story"),
                "home_file": home_item.get("file"),
                "home_has_coords": _has_home_coords(home_item) if home_item else False,
                "md": _file_meta(md_path),
                "html": _file_meta(html_path),
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "story_md": len(story_people),
            "story_html": len(html_people),
            "people_master": len(master),
            "people_master_pep": len(pep),
            "home_nodes": len(home),
            "birth_coords": len(coords),
        },
        "files": {
            "people_master": _file_meta(DATA_DIR / "people_master.json"),
            "people_master_pep": _file_meta(DATA_DIR / "people_master_pep.json"),
            "people_birth_coords_wgs84": _file_meta(DATA_DIR / "people_birth_coords_wgs84.json"),
            "stellar_home_data": _file_meta(HOME_DATA),
            "index_html": _file_meta(STORY_MAP_DIR / "index.html"),
            "map_html_renderer": _file_meta(REPO_ROOT / "storymap" / "script" / "map_html_renderer.py"),
            "build_stellar_homepage": _file_meta(REPO_ROOT / "tools" / "build_stellar_homepage.py"),
            "generate_pure_story_map": _file_meta(REPO_ROOT / "cli" / "generate_pure_story_map.py"),
        },
        "people": people_rows,
    }


def _build_validation_report() -> dict:
    story_people = set(_story_people())
    html_people = set(_canonical_html_people())
    master = _load_people_index(DATA_DIR / "people_master.json", "people")
    pep = _load_people_index(DATA_DIR / "people_master_pep.json", "people")
    home = _load_people_index(HOME_DATA, "nodes")
    coords = _load_coords_index(DATA_DIR / "people_birth_coords_wgs84.json")

    master_people = set(master.keys())
    pep_people = set(pep.keys())
    home_people = set(home.keys())
    coords_people = set(coords.keys())

    errors: list[dict] = []
    warnings: list[dict] = []

    def push_issue(bucket: list[dict], entry: dict | None) -> None:
        if entry:
            bucket.append(entry)

    push_issue(
        errors,
        _issue("story_missing_in_master", sorted(story_people - master_people), "error", "存在 Markdown 但未进入 people_master.json"),
    )
    push_issue(
        errors,
        _issue("story_missing_in_home", sorted(story_people - home_people), "error", "存在 Markdown 但未进入 stellar_home_data.json"),
    )
    push_issue(
        errors,
        _issue("story_missing_html", sorted(story_people - html_people), "error", "存在 Markdown 但缺少对应人物 HTML"),
    )
    push_issue(
        warnings,
        _issue("html_without_story", sorted(html_people - story_people), "warning", "存在人物 HTML，但没有对应 Markdown 源文件"),
    )
    push_issue(
        warnings,
        _issue("master_has_story_true_without_md", sorted([p for p, item in master.items() if bool(item.get("has_story")) and p not in story_people]), "warning", "people_master.json 中 has_story=true，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        _issue("home_without_story", sorted(home_people - story_people), "warning", "stellar_home_data.json 中存在节点，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        _issue("story_missing_coords", sorted(story_people - coords_people), "warning", "存在 Markdown 但出生地坐标缓存中没有对应人物"),
    )
    push_issue(
        warnings,
        _issue("pep_missing_in_master", sorted(pep_people - master_people), "warning", "people_master_pep.json 中的人物未出现在 people_master.json"),
    )

    master_has_story_false = []
    master_story_md_mismatch = []
    for p in sorted(story_people & master_people):
        item = master[p]
        if not bool(item.get("has_story")):
            master_has_story_false.append(p)
        expected_story_md = f"storymap/examples/story/{p}.md"
        if str(item.get("story_md") or "").strip() != expected_story_md:
            master_story_md_mismatch.append(p)
    push_issue(errors, _issue("master_has_story_false", master_has_story_false, "error", "people_master.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, _issue("master_story_md_mismatch", master_story_md_mismatch, "error", "people_master.json 中 story_md 路径与 Markdown 不一致"))

    home_has_story_false = []
    home_file_mismatch = []
    home_missing_coords = []
    for p in sorted(story_people & home_people):
        item = home[p]
        if item.get("has_story") is not True:
            home_has_story_false.append(p)
        expected_file = f"{p}.html"
        if str(item.get("file") or "").strip() != expected_file:
            home_file_mismatch.append(p)
        if not _has_home_coords(item):
            home_missing_coords.append(p)
    push_issue(errors, _issue("home_has_story_false", home_has_story_false, "error", "stellar_home_data.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, _issue("home_file_mismatch", home_file_mismatch, "error", "stellar_home_data.json 中 file 字段与人物 HTML 文件名不一致"))
    push_issue(warnings, _issue("home_missing_coords", home_missing_coords, "warning", "stellar_home_data.json 中存在节点，但缺少出生地坐标"))

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": len(errors) == 0,
        "summary": {
            "story_md": len(story_people),
            "story_html": len(html_people),
            "people_master": len(master_people),
            "people_master_pep": len(pep_people),
            "home_nodes": len(home_people),
            "birth_coords": len(coords_people),
            "error_count": sum(int(x.get("count", 0)) for x in errors),
            "warning_count": sum(int(x.get("count", 0)) for x in warnings),
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def _patch_master_with_has_story(master_fp: Path) -> dict:
    """按 .md 文件存在性强制刷新 has_story 与 story_md 字段。"""
    obj = json.loads(master_fp.read_text(encoding="utf-8"))
    people = obj.get("people", [])
    if not isinstance(people, list):
        return {"updated": 0, "total": 0}
    updated = 0
    for p in people:
        name = str(p.get("person", "")).strip()
        if not name:
            continue
        md_path = STORY_DIR / f"{name}.md"
        has_story = md_path.exists()
        was = bool(p.get("has_story"))
        if was != has_story:
            updated += 1
        p["has_story"] = has_story
        p["story_md"] = f"storymap/examples/story/{name}.md" if has_story else ""
    obj["count"] = len(people)
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    master_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(people)}


def _patch_home_with_has_story(home_fp: Path) -> dict:
    """给首页节点补 has_story 字段，源于 .md 存在性。"""
    obj = json.loads(home_fp.read_text(encoding="utf-8"))
    nodes = obj.get("nodes", [])
    if not isinstance(nodes, list):
        return {"updated": 0, "total": 0}
    updated = 0
    for n in nodes:
        name = str(n.get("person", "")).strip()
        if not name:
            continue
        md_path = STORY_DIR / f"{name}.md"
        has_story = md_path.exists()
        was = n.get("has_story")
        if was != has_story:
            updated += 1
        n["has_story"] = has_story
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    home_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(nodes)}


def main() -> int:
    ap = argparse.ArgumentParser(description="数据单源构建入口（幂等）")
    ap.add_argument("--skip-master", action="store_true")
    ap.add_argument("--skip-pep", action="store_true")
    ap.add_argument("--skip-html", action="store_true")
    ap.add_argument("--skip-home", action="store_true")
    ap.add_argument("--validate", action="store_true", help="构建结束后输出校验报告；若发现错误则返回非 0")
    ap.add_argument("--validate-only", action="store_true", help="只生成 manifest 与校验报告，不执行重建")
    ap.add_argument("--refresh-geocode", action="store_true",
                    help="重新跑一次高德地理编码（默认用现有缓存）")
    ap.add_argument("--fill-missing-md", action="store_true",
                    help="对 master 里没有 .md 的人物尝试 LLM 生成（需要 API key）")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    t0 = time.time()
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"[init] .md 源文件: {len(story_files)} 个, 已渲染 .html: {len(html_files)} 个")

    if args.validate_only:
        manifest = _build_manifest()
        report = _build_validation_report()
        _write_json(MANIFEST_JSON, manifest)
        _write_json(VALIDATION_JSON, report)
        print(f"[validate-only] manifest: {MANIFEST_JSON}")
        print(f"[validate-only] report:   {VALIDATION_JSON}")
        print(f"[validate-only] ok={report['ok']} errors={report['summary']['error_count']} warnings={report['summary']['warning_count']}")
        return 0 if report["ok"] else 2

    # ── 1. people_master.json ───────────────────────────────────
    if not args.skip_master:
        _print_section("1/5 rebuild data/people_master.json")
        rc = _run([
            sys.executable, "tools/build_people_master.py",
            "--scope", "all",
            "--out", str(DATA_DIR / "people_master.json"),
            "--concurrency", str(args.concurrency),
        ])
        if rc != 0:
            print(f"  ✗ build_people_master.py 退出码 {rc}", flush=True)
            return rc
        # 关键：用 .md 存在性强制覆盖 has_story
        master_fp = DATA_DIR / "people_master.json"
        stat = _patch_master_with_has_story(master_fp)
        print(f"  ✓ has_story 字段按 .md 存在性强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)

    # ── 2. people_master_pep.json ────────────────────────────────
    if not args.skip_pep:
        _print_section("2/5 rebuild data/people_master_pep.json")
        rc = _run([
            sys.executable, "tools/build_people_master.py",
            "--scope", "pep",
            "--out", str(DATA_DIR / "people_master_pep.json"),
            "--concurrency", str(args.concurrency),
        ])
        if rc != 0:
            print(f"  ✗ build_people_master.py (pep) 退出码 {rc}", flush=True)
            return rc
        # PEP 索引是教材口径的人物，用 .md 存在性刷 has_story
        pep_fp = DATA_DIR / "people_master_pep.json"
        stat = _patch_master_with_has_story(pep_fp)
        print(f"  ✓ pep has_story 字段按 .md 存在性强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)

    # ── 3. 增量重渲染人物页 ───────────────────────────────────────
    if not args.skip_html:
        _print_section("3/5 render changed story_map/*.html")
        rc = _run([
            sys.executable, "cli/generate_pure_story_map.py",
            "--render-changed",
            "--changed-mode", "nogeocode" if not args.refresh_geocode else "pure",
            "--changed-limit", "0",
        ])
        if rc != 0:
            print(f"  ✗ generate_pure_story_map.py --render-changed 退出码 {rc}", flush=True)
            return rc

    # ── 4. 出生地经纬度 ─────────────────────────────────────────
    _print_section("4/5 sync data/people_birth_coords_wgs84.json")
    if args.refresh_geocode:
        print("  → 重新跑 build_stellar_homepage.py 以触发 geocode（如果有缺失）", flush=True)
    # 后续 build_stellar_homepage 也会写 coords 文件，这里仅做提示

    # ── 5. stellar_home_data.json + index.html ──────────────────
    if not args.skip_home:
        _print_section("5/5 rebuild stellar_home_data.json + index.html")
        rc = _run([
            sys.executable, "tools/build_stellar_homepage.py",
            "--story-map-dir", str(STORY_MAP_DIR),
            "--story-md-dir", str(STORY_DIR),
        ])
        if rc != 0:
            print(f"  ✗ build_stellar_homepage.py 退出码 {rc}", flush=True)
            return rc
        # 强制 home 节点 has_story 一致
        if HOME_DATA.exists():
            stat = _patch_home_with_has_story(HOME_DATA)
            print(f"  ✓ home has_story 字段按 .md 存在性强制刷新: {stat['updated']} 处变更, {stat['total']} 节点", flush=True)

    # ── 收尾统计 ────────────────────────────────────────────────
    elapsed = time.time() - t0
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"\n[done] .md={len(story_files)} .html={len(html_files)}  耗时 {elapsed:.1f}s")
    if not story_files and not html_files:
        print("  ⚠ 警告：未找到 .md 源文件。请确认 storymap/examples/story/ 目录非空。")

    manifest = _build_manifest()
    report = _build_validation_report()
    _write_json(MANIFEST_JSON, manifest)
    _write_json(VALIDATION_JSON, report)
    print(f"[manifest] {MANIFEST_JSON}")
    print(f"[validate] {VALIDATION_JSON}  ok={report['ok']} errors={report['summary']['error_count']} warnings={report['summary']['warning_count']}")
    if args.validate and not report["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
