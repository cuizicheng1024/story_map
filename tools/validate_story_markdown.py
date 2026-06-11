#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import geocode_service as gs
import parsers as ps


REQUIRED_SECTION_PATTERNS = {
    "人物档案": re.compile(r"^##\s+(?:[一二三四五六七八九十]+、\s*)?人物档案\s*$", re.M),
    "基本信息": re.compile(r"^###\s+基本信息\s*$", re.M),
    "人生历程": re.compile(r"^##\s+(?:[一二三四五六七八九十]+、\s*)?人生历程与重要地点（按时间顺序）\s*$", re.M),
    "生平时间线": re.compile(r"^##\s+(?:[一二三四五六七八九十]+、\s*)?生平时间线\s*$", re.M),
}
REQUIRED_INFO_KEYS = ("姓名", "出生", "去世")
OPTIONAL_INFO_KEY_GROUPS = (("时代", "朝代"),)
LOCATION_HEADING = re.compile(r"^###\s+[🟢📍🔴].+$", re.M)
POSITION_FIELD = re.compile(r"^- \*\*(?:位置|地点)\*\*：", re.M)
PLACEHOLDER_LOCATION_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"待考",
        r"不详",
        r"未详",
        r"存疑",
        r"说法不一",
        r"虚构地点",
        r"无法定位",
        r"争议地区",
    ]
]
VAGUE_LOCATION_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"(境内|诸地|各地|一带|附近|周边|沿线|流域|地区)$",
        r"^(北方|南方|西方|东方|中原|关中|江南|塞外|岭南)(?:诸地|各地|一带|地区)?$",
    ]
]


@dataclass
class ValidationResult:
    file_path: Path
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _result_to_dict(result: ValidationResult) -> dict:
    return {
        "file": str(result.file_path.relative_to(REPO_ROOT)),
        "ok": result.ok,
        "errors": list(result.errors),
        "warnings": list(result.warnings),
    }


def _section_slice(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^###\s+{re.escape(heading)}\s*$", re.M)
    match = pattern.search(markdown)
    if not match:
        return ""
    start = match.end()
    tail = markdown[start:]
    next_heading = re.search(r"^##?\s+", tail, re.M)
    end = start + next_heading.start() if next_heading else len(markdown)
    return markdown[start:end]


def _is_placeholder_location(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw or raw in {"-", "—", "——"}:
        return True
    return any(pattern.search(raw) for pattern in PLACEHOLDER_LOCATION_PATTERNS)


def _is_vague_location(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(pattern.search(raw) for pattern in VAGUE_LOCATION_PATTERNS)


def _resolve_location_offline_candidates(
    location_text: str,
    fallback_name: str = "",
    *,
    coords_cache: dict | None = None,
    coords_search_map: dict | None = None,
) -> tuple[bool, str]:
    location = str(location_text or "").strip()
    if not location and fallback_name:
        location = str(fallback_name).strip()
    if not location:
        return False, ""
    ancient, modern = gs.split_ancient_modern(location)
    geo = ps._pick_geocode_name(modern or location)
    search_name = ""
    for candidate in [
        geo,
        ps._pick_geocode_name(modern) if modern else "",
        ps._pick_geocode_name(location) if location else "",
        ps._pick_geocode_name(fallback_name) if fallback_name else "",
    ]:
        if candidate and candidate in (coords_search_map or {}):
            search_name = (coords_search_map or {}).get(candidate, "")
            break
    direct_pair = ps._extract_inline_coord_pair(location)
    if direct_pair:
        return True, modern or ancient or location
    coord = gs.fuzzy_coord_lookup(
        coords_cache or {},
        [geo, modern, location, fallback_name, ancient],
    )
    if not coord:
        coord = gs.lookup_coords_from_historical_index(geo, search_name, modern, location, fallback_name)
    return coord is not None, modern or ancient or location


def validate_markdown(file_path: Path) -> ValidationResult:
    text = file_path.read_text(encoding="utf-8")
    result = ValidationResult(file_path=file_path)
    parsed_doc = ps.parse_story_document(text)
    coords_cache = parsed_doc.coords_table
    coords_search_map = parsed_doc.coords_search_map

    if not re.search(r"^#\s+.+$", text, re.M):
        result.errors.append("缺少一级标题 `# 人物名`")

    for label, pattern in REQUIRED_SECTION_PATTERNS.items():
        if not pattern.search(text):
            result.errors.append(f"缺少必需章节：{label}")

    basic_info = _section_slice(text, "基本信息")
    if basic_info:
        for key in REQUIRED_INFO_KEYS:
            if not re.search(rf"^- \*\*{re.escape(key)}\*\*：", basic_info, re.M):
                result.errors.append(f"`基本信息` 缺少字段：{key}")
        for group in OPTIONAL_INFO_KEY_GROUPS:
            if not any(re.search(rf"^- \*\*{re.escape(key)}\*\*：", basic_info, re.M) for key in group):
                result.errors.append(f"`基本信息` 缺少字段组：{' / '.join(group)}")

    location_sections = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    if REQUIRED_SECTION_PATTERNS["人生历程"].search(text):
        if not LOCATION_HEADING.search(text):
            result.errors.append("`人生历程与重要地点` 章节缺少地点小节标题")
        if not POSITION_FIELD.search(text):
            result.errors.append("`人生历程与重要地点` 章节缺少 `位置` 字段")
        if not location_sections:
            result.errors.append("`人生历程与重要地点` 章节无法解析出结构化地点小节")
        unresolved_locations: List[str] = []
        vague_locations: List[str] = []
        for idx, item in enumerate(location_sections, start=1):
            loc_name = str(item.get("name") or "").strip()
            label = loc_name or f"第{idx}个地点"
            location_text = str(item.get("location") or "").strip()
            if not str(item.get("time") or "").strip():
                result.errors.append(f"`{label}` 缺少时间字段")
            if not location_text:
                result.errors.append(f"`{label}` 缺少位置字段")
                continue
            if not str(item.get("event") or "").strip():
                result.warnings.append(f"`{label}` 缺少事迹/经过字段")
            if not str(item.get("significance") or "").strip():
                result.warnings.append(f"`{label}` 缺少意义字段")
            if _is_vague_location(location_text):
                vague_locations.append(label)
            resolved, resolved_name = _resolve_location_offline_candidates(
                location_text,
                loc_name,
                coords_cache=coords_cache,
                coords_search_map=coords_search_map,
            )
            if (not resolved) and (not _is_placeholder_location(location_text)):
                unresolved_locations.append(resolved_name or label)
        if vague_locations:
            preview = "、".join(vague_locations[:5])
            extra = "" if len(vague_locations) <= 5 else f" 等 {len(vague_locations)} 个地点"
            result.errors.append(f"存在泛地名，无法保证定位精度：{preview}{extra}")
        if unresolved_locations:
            preview = "、".join(unresolved_locations[:5])
            extra = "" if len(unresolved_locations) <= 5 else f" 等 {len(unresolved_locations)} 个地点"
            result.warnings.append(f"离线坐标未命中：{preview}{extra}")

    if REQUIRED_SECTION_PATTERNS["生平时间线"].search(text):
        timeline_header = [str(item or "").strip() for item in list(parsed_doc.timeline_header or [])]
        header_text = " | ".join(timeline_header)
        if not timeline_header:
            result.errors.append("`生平时间线` 章节缺少可解析表头")
        else:
            if not any("年份" in col for col in timeline_header):
                result.errors.append("`生平时间线` 表头缺少 `年份` 列")
            if not any(("事件" in col) or ("关键事件" in col) for col in timeline_header):
                result.errors.append("`生平时间线` 表头缺少 `事件` / `关键事件` 列")
            if len(timeline_header) < 3:
                result.errors.append(f"`生平时间线` 表头列数不足：{header_text}")

    locations = []
    for item in location_sections:
        loc_text = str(item.get("location") or item.get("name") or "").strip()
        if not loc_text:
            continue
        resolved, _ = _resolve_location_offline_candidates(
            loc_text,
            str(item.get("name") or "").strip(),
            coords_cache=coords_cache,
            coords_search_map=coords_search_map,
        )
        if resolved:
            locations.append(item)
    if not locations:
        result.warnings.append("未解析出任何地点，静态人物页可能显示为空时间轴")
    if location_sections:
        expected = len(location_sections)
        actual = len(locations)
        if actual < expected:
            result.warnings.append(f"地点解析存在落差：结构化地点 {expected} 个，但离线模式仅保留 {actual} 个")
        if expected >= 5 and actual <= max(1, expected // 3):
            result.errors.append(f"离线命中率过低：{expected} 个地点仅命中 {actual} 个，请补充地点词典或修正地点字段")

    birth_text = str(parsed_doc.basic_info_map.get("出生", "") or "")
    death_text = str(parsed_doc.basic_info_map.get("去世", "") or "")
    _, birth_loc = ps._parse_date_location(birth_text, ["出生于", "生于"])
    _, death_loc = ps._parse_date_location(death_text, ["卒于", "去世于", "卒"])
    if not birth_loc:
        result.warnings.append("未解析出出生地")
    if not death_loc:
        result.warnings.append("未解析出去世地")

    return result


def _resolve_input_files(story_dir: Path, raw_files: List[str]) -> List[Path]:
    if not raw_files:
        return sorted(story_dir.glob("*.md"))
    resolved: List[Path] = []
    for raw in raw_files:
        p = Path(raw)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if p.exists() and p.suffix.lower() == ".md":
            resolved.append(p)
            continue
        alt = (story_dir / raw).resolve()
        if alt.exists() and alt.suffix.lower() == ".md":
            resolved.append(alt)
    unique = []
    seen = set()
    for p in resolved:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="校验人物 Markdown 是否符合 StoryMap 推荐格式")
    parser.add_argument(
        "--story-dir",
        default=str(REPO_ROOT / "storymap" / "examples" / "story"),
        help="人物 Markdown 目录",
    )
    parser.add_argument("--files", nargs="*", default=[], help="只校验指定 Markdown 文件")
    parser.add_argument("--strict", action="store_true", help="有 warning 也返回非 0")
    parser.add_argument("--report-json", default="", help="将校验结果写入 JSON 报告")
    args = parser.parse_args()

    story_dir = Path(args.story_dir).resolve()
    files = _resolve_input_files(story_dir, list(args.files or []))
    if not files:
        print(f"[ERROR] 未找到 Markdown 文件：{story_dir}")
        return 1

    report_items = []
    error_count = 0
    warning_count = 0
    for file_path in files:
        result = validate_markdown(file_path)
        report_items.append(_result_to_dict(result))
        if result.errors:
            error_count += 1
        if result.warnings:
            warning_count += 1
        if not result.errors and not result.warnings:
            continue
        print(f"\n[{file_path.name}]")
        for message in result.errors:
            print(f"  ERROR: {message}")
        for message in result.warnings:
            print(f"  WARN : {message}")

    print(f"\nSummary: files={len(files)} error_files={error_count} warning_files={warning_count}")
    if args.report_json:
        report_path = Path(args.report_json)
        if not report_path.is_absolute():
            report_path = (REPO_ROOT / report_path).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "summary": {
                        "files": len(files),
                        "error_files": error_count,
                        "warning_files": warning_count,
                    },
                    "results": report_items,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if error_count:
        return 1
    if args.strict and warning_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
