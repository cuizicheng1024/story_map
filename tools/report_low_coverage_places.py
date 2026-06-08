#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import geocode_service as gs
import parsers as ps


def _resolve_search_name(coords_search_map: Dict[str, str], geo_name: str, modern: str, loc_text: str, raw_name: str) -> str:
    for candidate in [
        geo_name,
        ps._pick_geocode_name(modern) if modern else "",
        ps._pick_geocode_name(loc_text) if loc_text else "",
        ps._pick_geocode_name(raw_name) if raw_name else "",
    ]:
        if candidate and candidate in coords_search_map:
            return coords_search_map[candidate]
    return ""


def _resolve_offline_coord(coords_cache: Dict[str, Tuple[float, float]], coords_search_map: Dict[str, str], loc_text: str, raw_name: str = "") -> Optional[Tuple[float, float]]:
    ancient, modern = gs.split_ancient_modern(loc_text)
    geo_name = ps._pick_geocode_name(modern or loc_text or raw_name or ancient)
    coord = gs.fuzzy_coord_lookup(
        coords_cache,
        [
            geo_name,
            modern,
            loc_text,
            raw_name,
            ancient,
        ],
    )
    search_name = _resolve_search_name(coords_search_map, geo_name, modern, loc_text, raw_name)
    if not coord:
        coord = gs.lookup_coords_from_historical_index(
            geo_name,
            search_name,
            ancient,
            modern,
            loc_text,
            raw_name,
        )
    return coord


def _collect_candidate_points(md_text: str) -> dict:
    parsed_doc = ps.parse_story_document(md_text)
    info = parsed_doc.basic_info_map or {}
    coords_cache = parsed_doc.coords_table
    coords_search_map = parsed_doc.coords_search_map
    birth_text = str(info.get("出生", "") or "")
    death_text = str(info.get("去世", "") or "")
    _, birth_loc = ps._parse_date_location(birth_text, ["出生于", "生于"])
    _, death_loc = ps._parse_date_location(death_text, ["卒于", "去世于", "卒"])
    sections = ps._parse_location_sections(md_text) or []

    raw_locations: List[str] = []
    unresolved_locations: List[str] = []
    rendered_location_count = 0
    for loc in sections:
        loc_text = str(loc.get("location") or loc.get("name") or "").strip()
        raw_name = str(loc.get("name") or "").strip()
        if not loc_text:
            continue
        raw_locations.append(loc_text)
        if not _resolve_offline_coord(coords_cache, coords_search_map, loc_text, raw_name):
            unresolved_locations.append(loc_text)
        else:
            rendered_location_count += 1

    birth_has_coord = bool(birth_loc and _resolve_offline_coord(coords_cache, coords_search_map, birth_loc, birth_loc))
    death_has_coord = bool(death_loc and _resolve_offline_coord(coords_cache, coords_search_map, death_loc, death_loc))
    return {
        "birth_loc": birth_loc,
        "death_loc": death_loc,
        "birth_has_coord": birth_has_coord,
        "death_has_coord": death_has_coord,
        "raw_locations": raw_locations,
        "rendered_location_count": rendered_location_count,
        "unresolved_locations": unresolved_locations,
    }


def build_report(story_dir: Path, limit: int) -> dict:
    rows = []
    unresolved_counter: Counter[str] = Counter()
    files = sorted(story_dir.glob("*.md"))
    for file_path in files:
        md_text = file_path.read_text(encoding="utf-8")
        points = _collect_candidate_points(md_text)
        raw_locations = list(points["raw_locations"])
        unresolved_locations = list(points["unresolved_locations"])
        rendered_locations = int(points["rendered_location_count"])
        raw_count = len(raw_locations)
        missing_count = max(raw_count - rendered_locations, 0)
        birth_missing = bool(points["birth_loc"]) and not bool(points["birth_has_coord"])
        death_missing = bool(points["death_loc"]) and not bool(points["death_has_coord"])
        score = missing_count * 10 + len(unresolved_locations) * 3 + int(birth_missing) + int(death_missing)
        if missing_count <= 0 and not unresolved_locations and not birth_missing and not death_missing:
            continue
        for loc in unresolved_locations:
            unresolved_counter[loc] += 1
        rows.append(
            {
                "person": file_path.stem,
                "raw_location_count": raw_count,
                "rendered_location_count": rendered_locations,
                "missing_location_count": missing_count,
                "coverage_ratio": round(rendered_locations / raw_count, 4) if raw_count else 1.0,
                "birth_location": points["birth_loc"],
                "birth_missing_coord": birth_missing,
                "death_location": points["death_loc"],
                "death_missing_coord": death_missing,
                "unresolved_locations": unresolved_locations,
                "score": score,
                "file": str(file_path.relative_to(REPO_ROOT)),
            }
        )

    rows.sort(key=lambda item: (-int(item["score"]), float(item["coverage_ratio"]), item["person"]))
    hot_places = [{"location": name, "count": count} for name, count in unresolved_counter.most_common(limit)]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "story_dir": str(story_dir.relative_to(REPO_ROOT)),
        "summary": {
            "files": len(files),
            "low_coverage_people": len(rows),
        },
        "top_people": rows[:limit],
        "hot_unresolved_places": hot_places,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# 低覆盖离线地名清单",
        "",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- 扫描目录：`{report.get('story_dir', '')}`",
        f"- 低覆盖人物数：`{report.get('summary', {}).get('low_coverage_people', 0)}`",
        "",
        "## 优先补点人物",
        "",
        "| 人物 | 原始地点数 | 当前离线命中 | 缺失数 | 覆盖率 | 出生地缺坐标 | 去世地缺坐标 | 缺失地点样本 |",
        "| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :--- |",
    ]
    for item in report.get("top_people", []):
        samples = "、".join(list(item.get("unresolved_locations", []))[:4]) or "-"
        lines.append(
            "| {person} | {raw} | {rendered} | {missing} | {ratio:.0%} | {birth} | {death} | {samples} |".format(
                person=item.get("person", ""),
                raw=int(item.get("raw_location_count", 0)),
                rendered=int(item.get("rendered_location_count", 0)),
                missing=int(item.get("missing_location_count", 0)),
                ratio=float(item.get("coverage_ratio", 0.0)),
                birth="是" if item.get("birth_missing_coord") else "否",
                death="是" if item.get("death_missing_coord") else "否",
                samples=samples,
            )
        )
    lines.extend(
        [
            "",
            "## 高频未命中地名",
            "",
            "| 地名 | 命中失败次数 |",
            "| :--- | ---: |",
        ]
    )
    for item in report.get("hot_unresolved_places", []):
        lines.append(f"| {item.get('location', '')} | {int(item.get('count', 0))} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="统计静态模式下离线地名覆盖较低的人物与地点")
    parser.add_argument("--story-dir", default=str(REPO_ROOT / "storymap" / "examples" / "story"))
    parser.add_argument("--out-json", default=str(REPO_ROOT / "data" / "low_coverage_story_report.json"))
    parser.add_argument("--out-md", default=str(REPO_ROOT / "data" / "low_coverage_story_report.md"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    story_dir = Path(args.story_dir).resolve()
    report = build_report(story_dir, max(1, int(args.limit)))

    out_json = Path(args.out_json)
    if not out_json.is_absolute():
        out_json = (REPO_ROOT / out_json).resolve()
    out_md = Path(args.out_md)
    if not out_md.is_absolute():
        out_md = (REPO_ROOT / out_md).resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")

    print(f"[report] json={out_json}")
    print(f"[report] md={out_md}")
    print(
        "[summary] files={files} low_coverage_people={people}".format(
            files=int(report.get("summary", {}).get("files", 0)),
            people=int(report.get("summary", {}).get("low_coverage_people", 0)),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
