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

import story_map as sm


REQUIRED_SECTION_PATTERNS = {
    "人物档案": re.compile(r"^##\s+一、人物档案\s*$", re.M),
    "基本信息": re.compile(r"^###\s+基本信息\s*$", re.M),
    "人生历程": re.compile(r"^##\s+三、人生历程与重要地点（按时间顺序）\s*$", re.M),
    "生平时间线": re.compile(r"^##\s+四、生平时间线\s*$", re.M),
}
REQUIRED_INFO_KEYS = ("姓名", "出生", "去世")
OPTIONAL_INFO_KEY_GROUPS = (("时代", "朝代"),)
TIMELINE_HEADER = re.compile(r"^\|\s*年份\s*\|\s*年龄\s*\|\s*关键事件\s*\|", re.M)
LOCATION_HEADING = re.compile(r"^###\s+[🟢📍🔴].+$", re.M)
POSITION_FIELD = re.compile(r"^- \*\*位置\*\*：", re.M)


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


def validate_markdown(file_path: Path) -> ValidationResult:
    text = file_path.read_text(encoding="utf-8")
    result = ValidationResult(file_path=file_path)

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

    if REQUIRED_SECTION_PATTERNS["人生历程"].search(text):
        if not LOCATION_HEADING.search(text):
            result.errors.append("`人生历程与重要地点` 章节缺少地点小节标题")
        if not POSITION_FIELD.search(text):
            result.errors.append("`人生历程与重要地点` 章节缺少 `位置` 字段")

    if REQUIRED_SECTION_PATTERNS["生平时间线"].search(text) and not TIMELINE_HEADER.search(text):
        result.errors.append("`生平时间线` 章节缺少标准表头 `年份 | 年龄 | 关键事件`")

    profile = sm._load_profile_from_md(text, allow_geocode=False)
    if not profile:
        result.errors.append("解析失败：`_load_profile_from_md()` 返回空结果")
        return result

    locations = list(profile.get("locations") or [])
    if not locations:
        result.warnings.append("未解析出任何地点，静态人物页可能显示为空时间轴")
    if len(locations) < 3:
        result.warnings.append(f"仅解析出 {len(locations)} 个地点，建议补充地点章节或离线坐标别名")

    birth = (profile.get("person") or {}).get("birth") or {}
    death = (profile.get("person") or {}).get("death") or {}
    if not birth.get("location"):
        result.warnings.append("未解析出出生地")
    if not death.get("location"):
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
