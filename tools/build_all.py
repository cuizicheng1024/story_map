#!/usr/bin/env python3
"""build_all.py - 数据单源构建入口

职责：
  1. 重新生成 data/people_master.json（教材总索引）
  2. 重新生成 data/people_master_pep.json（PEP 教材人物）
  3. 重新生成 data/pep_people_spotlight.json（PEP 重点人物）
  4. 重新生成 data/people_birth_coords_wgs84.json（出生地经纬度）
  5. 重新生成 storymap/examples/story_map/stellar_home_data.json + index.html

数据源：单一来源 = storymap/examples/story/*.md
幂等：默认不会触发 LLM 补缺、不会重新 geocode。带 --refresh-geocode 时重新跑一次地理编码。
"""
from __future__ import annotations

import argparse
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


def _existing_htmls() -> set[str]:
    if not STORY_MAP_DIR.exists():
        return set()
    return {p.stem for p in STORY_MAP_DIR.glob("*.html")}


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
    ap.add_argument("--skip-home", action="store_true")
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

    # ── 1. people_master.json ───────────────────────────────────
    if not args.skip_master:
        _print_section("1/4 rebuild data/people_master.json")
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
        _print_section("2/4 rebuild data/people_master_pep.json")
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

    # ── 3. 出生地经纬度 ─────────────────────────────────────────
    _print_section("3/4 sync data/people_birth_coords_wgs84.json")
    if args.refresh_geocode:
        print("  → 重新跑 build_stellar_homepage.py 以触发 geocode（如果有缺失）", flush=True)
    # 后续 build_stellar_homepage 也会写 coords 文件，这里仅做提示

    # ── 4. stellar_home_data.json + index.html ──────────────────
    if not args.skip_home:
        _print_section("4/4 rebuild stellar_home_data.json + index.html")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
