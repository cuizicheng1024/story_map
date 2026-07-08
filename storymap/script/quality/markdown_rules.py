from __future__ import annotations

import re
from typing import Any

from .issues import make_issue
from .text_rules import cn_to_int, get_think_patterns

MODERN_DYNASTIES = {"清", "近现代", "现代", "民国", "中华人民共和国", "清代"}
FEUDAL_LABELS = {"君臣", "君主", "臣子", "主仆", "主臣", "君臣关系"}
THINK_PATTERNS = get_think_patterns()


def check_short_review(data: dict[str, Any]) -> list[dict[str, Any]]:
    person = data.get("person", {}) or {}
    short_review = person.get("shortReview", "") or person.get("short_review", "")
    if not short_review or len(str(short_review).strip()) < 2:
        return [make_issue(
            "MISSING_SHORT_REVIEW",
            "short_review",
            "warning",
            "short_review 为空或过短",
            field="person.shortReview",
            auto_fixable=True,
            confidence=0.95,
            source="quality.markdown_rules",
        )]
    return []


def check_think_leak(data: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    person = data.get("person", {}) or {}
    fields = [("person.description", person.get("description", "")), ("markdown", data.get("markdown", ""))]
    for field, content in fields:
        if not content:
            continue
        text = str(content)
        for pattern in THINK_PATTERNS:
            match = pattern.search(text)
            if match:
                snippet = text[max(0, match.start() - 20):match.end() + 40].replace("\n", " ")[:100]
                issues.append(make_issue(
                    "LLM_THINK_LEAK",
                    "think_leak",
                    "error",
                    f'{field} 包含 LLM 思考过程: "{snippet}..."',
                    field=field,
                    auto_fixable=True,
                    confidence=0.85,
                    source="quality.markdown_rules",
                    details={"snippet": snippet},
                ))
                break
    return issues


def check_coordinates(data: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    locations = data.get("locations", []) or []
    if not locations:
        return [make_issue(
            "EMPTY_LOCATIONS",
            "coord",
            "warning",
            "locations 数组为空",
            field="locations",
            auto_fixable=False,
            confidence=0.9,
            source="quality.markdown_rules",
        )]
    for i, loc in enumerate(locations):
        loc = loc or {}
        lat = loc.get("lat")
        lng = loc.get("lng") or loc.get("lon")
        name = loc.get("name", f"位置{i}")
        field = f"locations[{i}]"
        if lat is None or lng is None:
            issues.append(make_issue(
                "MISSING_COORDINATE",
                "coord",
                "warning",
                f"坐标缺失: {name}",
                field=field,
                auto_fixable=True,
                confidence=0.9,
                source="quality.markdown_rules",
                details={"location": name},
            ))
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (ValueError, TypeError):
            issues.append(make_issue("INVALID_COORDINATE_FORMAT", "coord", "error", f"坐标格式异常: {name}", field=field, auto_fixable=False, source="quality.markdown_rules"))
            continue
        if abs(lat_f) >= 90:
            issues.append(make_issue("LATITUDE_OUT_OF_RANGE", "coord", "error", f"纬度越界: {name} lat={lat_f}", field=f"{field}.lat", auto_fixable=False, source="quality.markdown_rules"))
        if abs(lng_f) >= 180:
            issues.append(make_issue("LONGITUDE_OUT_OF_RANGE", "coord", "error", f"经度越界: {name} lng={lng_f}", field=f"{field}.lng", auto_fixable=False, source="quality.markdown_rules"))
        if lat_f == 0.0 and lng_f == 0.0:
            issues.append(make_issue("ZERO_COORDINATE", "coord", "warning", f"坐标为(0,0): {name}", field=field, auto_fixable=True, source="quality.markdown_rules"))
        geocode_confidence = loc.get("geocodeConfidence")
        if geocode_confidence is not None:
            try:
                confidence_f = float(geocode_confidence)
            except (ValueError, TypeError):
                issues.append(make_issue("GEO_CONFIDENCE_INVALID", "coord", "warning", f"地理编码置信度格式异常: {name}", field=f"{field}.geocodeConfidence", auto_fixable=False, source="quality.markdown_rules"))
            else:
                if confidence_f < 0.75:
                    issues.append(make_issue(
                        "GEO_LOW_CONFIDENCE",
                        "coord",
                        "warning",
                        f"地理编码置信度偏低: {name} confidence={confidence_f}",
                        field=f"{field}.geocodeConfidence",
                        auto_fixable=False,
                        confidence=confidence_f,
                        source="quality.markdown_rules",
                        details={"location": name, "threshold": 0.75},
                    ))
    return issues


def check_chapters(data_or_markdown: dict[str, Any] | str) -> list[dict[str, Any]]:
    markdown = data_or_markdown if isinstance(data_or_markdown, str) else data_or_markdown.get("markdown", "")
    if not markdown:
        return []
    chapters: list[int] = []
    for m in re.finditer(r'^##\s+([一二三四五六七八九十]+)[、，\.\s]', str(markdown), re.MULTILINE):
        num = cn_to_int(m.group(1))
        if num is not None:
            chapters.append(num)
    if not chapters:
        return []
    issues: list[dict[str, Any]] = []
    sorted_ch = sorted(set(chapters))
    if len(sorted_ch) != len(chapters):
        duplicates = sorted(set(c for c in chapters if chapters.count(c) > 1))
        issues.append(make_issue(
            "DUPLICATE_CHAPTER_NUMBER",
            "chapter",
            "warning",
            f"重复章节编号: {duplicates}",
            field="markdown",
            auto_fixable=True,
            confidence=0.95,
            source="quality.markdown_rules",
            details={"duplicates": duplicates},
        ))
    if len(sorted_ch) > 1 and sorted_ch != list(range(sorted_ch[0], sorted_ch[-1] + 1)):
        missing = sorted(set(range(sorted_ch[0], sorted_ch[-1] + 1)) - set(sorted_ch))
        if missing:
            issues.append(make_issue(
                "NON_CONTIGUOUS_CHAPTER_NUMBER",
                "chapter",
                "warning",
                f"章节不连续，缺少: {missing}",
                field="markdown",
                auto_fixable=True,
                confidence=0.95,
                source="quality.markdown_rules",
                details={"missing": missing},
            ))
    return issues


def check_relations(data: dict[str, Any]) -> list[dict[str, Any]]:
    person = data.get("person", {}) or {}
    if person.get("dynasty", "") not in MODERN_DYNASTIES:
        return []
    issues: list[dict[str, Any]] = []
    links = (data.get("relatedGraph", {}) or {}).get("links", []) or []
    for i, link in enumerate(links):
        label = (link or {}).get("label", "")
        if any(fl in label for fl in FEUDAL_LABELS):
            issues.append(make_issue(
                "FEUDAL_RELATION_LABEL_FOR_MODERN_PERSON",
                "relation",
                "warning",
                f"关系措辞不当: {link.get('source', '?')} → {link.get('target', '?')} = '{label}'",
                field=f"relatedGraph.links[{i}].label",
                auto_fixable=False,
                confidence=0.85,
                source="quality.markdown_rules",
            ))
    return issues


def check_placeholders(data_or_markdown: dict[str, Any] | str) -> list[dict[str, Any]]:
    markdown = data_or_markdown if isinstance(data_or_markdown, str) else data_or_markdown.get("markdown", "")
    if not markdown:
        return [make_issue("EMPTY_MARKDOWN", "markdown", "error", "markdown 字段为空", field="markdown", auto_fixable=False, source="quality.markdown_rules")]
    text = str(markdown)
    issues: list[dict[str, Any]] = []
    placeholder_count = text.count("待补充")
    if placeholder_count > 3:
        issues.append(make_issue(
            "TOO_MANY_PLACEHOLDERS",
            "markdown",
            "warning",
            f"markdown 包含 {placeholder_count} 处'待补充'占位符",
            field="markdown",
            auto_fixable=True,
            confidence=0.9,
            source="quality.markdown_rules",
            details={"placeholder": "待补充", "count": placeholder_count},
        ))
    if "暂无可用" in text:
        issues.append(make_issue(
            "NO_AVAILABLE_PLACEHOLDER",
            "markdown",
            "warning",
            "markdown 包含'暂无可用'占位符",
            field="markdown",
            auto_fixable=True,
            confidence=0.9,
            source="quality.markdown_rules",
            details={"placeholder": "暂无可用"},
        ))
    return issues


def run_html_quality_checks(data: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(check_short_review(data))
    issues.extend(check_think_leak(data))
    issues.extend(check_coordinates(data))
    issues.extend(check_chapters(data))
    issues.extend(check_relations(data))
    issues.extend(check_placeholders(data))
    return issues


__all__ = [
    "check_chapters",
    "check_coordinates",
    "check_placeholders",
    "check_relations",
    "check_short_review",
    "check_think_leak",
    "run_html_quality_checks",
]
