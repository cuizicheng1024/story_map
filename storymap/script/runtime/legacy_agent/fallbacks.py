from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from ...core import parsers as parser_utils
from .state import StoryAgentState


def fallback_search_result(person: str, state: StoryAgentState) -> Dict[str, object]:
    existing = state.get("search_result") or {}
    if isinstance(existing, dict) and existing.get("person"):
        return dict(existing)
    return {
        "person": person,
        "sources": [],
        "source_names": [],
        "dynasty": "",
        "summary": "",
        "identities": [],
        "achievements": [],
        "timeline": [],
        "places": [],
        "cautions": ["未完成联网检索，已使用降级资料结构。"],
    }


def place_map_lookup(place_maps: List[Dict[str, object]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in place_maps:
        if not isinstance(item, dict):
            continue
        keys = [
            parser_utils._normalize_place_key(str(item.get("query") or "")),
            parser_utils._normalize_place_key(str(item.get("ancient_name") or "")),
            parser_utils._normalize_place_key(str(item.get("modern_name") or "")),
        ]
        modern = str(item.get("modern_name") or "").strip()
        if not modern:
            continue
        for key in keys:
            if key:
                mapping[key] = modern
    return mapping


def format_year_text(text: object) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    if "年" in content:
        return content
    if re.search(r"\d", content):
        return f"{content}年"
    return content


def fallback_generate_markdown(
    structure: Dict[str, object],
    *,
    infer_dynasty: Optional[Callable[..., str]] = None,
) -> str:
    person = str(structure.get("person") or "").strip() or "未知人物"
    search_result = structure.get("search_result") if isinstance(structure.get("search_result"), dict) else {}
    search_result = dict(search_result or {})
    place_maps = [item for item in structure.get("place_maps") or [] if isinstance(item, dict)]
    place_lookup = place_map_lookup(place_maps)
    timeline = [item for item in search_result.get("timeline") or [] if isinstance(item, dict)]
    identities = [str(item).strip() for item in search_result.get("identities") or [] if str(item).strip()]
    achievements = [str(item).strip() for item in search_result.get("achievements") or [] if str(item).strip()]
    cautions = [str(item).strip() for item in search_result.get("cautions") or [] if str(item).strip()]
    summary = str(search_result.get("summary") or "").strip() or f"{person} 的资料暂不完整，以下内容为降级整理稿。"
    infer_dynasty_fn = infer_dynasty or (lambda *_args: "")
    dynasty = str(search_result.get("dynasty") or "").strip() or infer_dynasty_fn(
        summary,
        " ".join(identities),
        " ".join(achievements),
    )

    birth_line = ""
    death_line = ""
    location_sections: List[Dict[str, str]] = []
    seen_locations = set()
    for item in timeline:
        year = format_year_text(item.get("year"))
        place = str(item.get("place") or "").strip()
        event = str(item.get("event") or "").strip()
        normalized = parser_utils._normalize_place_key(place)
        modern = place_lookup.get(normalized, place)
        if ("出生" in event) and not birth_line:
            birth_line = f"{year}，{place}（今{modern}）" if modern and modern != place else f"{year}，{place}"
        if (("卒" in event) or ("逝" in event) or ("去世" in event)) and not death_line:
            death_line = f"{year}，{place}（今{modern}）" if modern and modern != place else f"{year}，{place}"
        section_key = (place, modern, event)
        if place and section_key not in seen_locations:
            seen_locations.add(section_key)
            if "出生" in event:
                heading = f"### 🟢 出生地：{place}"
                event_label = "事迹"
            elif (("卒" in event) or ("逝" in event) or ("去世" in event)):
                heading = f"### 🔴 去世地：{place}"
                event_label = "经过"
            else:
                heading = f"### 📍 重要地点：{place}"
                event_label = "事迹"
            location_sections.append(
                {
                    "heading": heading,
                    "year": year,
                    "location": f"{place}（今{modern}）" if modern and modern != place else (modern or place),
                    "event_label": event_label,
                    "event": event or "暂无相关事迹",
                }
            )

    lines = [
        f"# {person}",
        "",
        "## 一、人物档案",
        "",
        "### 基本信息",
        f"- **姓名**：{person}",
        f"- **时代**：{dynasty}",
        f"- **出生**：{birth_line}",
        f"- **去世**：{death_line}",
        f"- **主要身份**：{'、'.join(identities)}",
        f"- **主要成就**：{'；'.join(achievements[:4])}",
        "",
        "### 生平概述",
        summary,
        "",
        "## 三、人生历程与重要地点（按时间顺序）",
        "",
    ]
    if location_sections:
        for section in location_sections:
            lines.extend(
                [
                    section["heading"],
                    f"- **公元纪年**：{section['year']}",
                    f"- **位置**：{section['location']}",
                    f"- **{section['event_label']}**：{section['event']}",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "### 📍 重要地点：待补充",
                "- **公元纪年**：待补充",
                "- **位置**：待补充",
                "- **事迹**：暂无可用地点资料",
                "",
            ]
        )
    lines.extend(
        [
            "## 四、生平时间线",
            "",
            "| 年份 | 古称 | 现称 | 事件 |",
            "| --- | --- | --- | --- |",
        ]
    )
    if timeline:
        for item in timeline:
            year = format_year_text(item.get("year"))
            place = str(item.get("place") or "").strip()
            event = str(item.get("event") or "").strip()
            normalized = parser_utils._normalize_place_key(place)
            modern = place_lookup.get(normalized, place)
            lines.append(f"| {year} | {place} | {modern} | {event} |")
    else:
        lines.append("|  |  |  | 暂无可用时间线资料 |")
    if cautions:
        lines.extend(["", "## 五、补充说明", ""])
        for item in cautions:
            lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def fallback_validation(
    content: str,
    *,
    person: str = "",
    validate_fn: Optional[Callable[..., Dict[str, object]]] = None,
) -> Dict[str, object]:
    if callable(validate_fn):
        try:
            return validate_fn(content, person=person)
        except TypeError:
            return validate_fn(content)
    return {
        "pass": False,
        "risk_level": "high",
        "issues": [],
        "notes": "未提供降级校验器",
    }


__all__ = [
    "fallback_generate_markdown",
    "fallback_search_result",
    "fallback_validation",
    "format_year_text",
    "place_map_lookup",
]
