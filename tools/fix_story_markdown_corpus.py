#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import map_client as mc


NON_AUTHENTIC_FILES = {
    "唐银平.md",
    "阿城.md",
    "于文豪.md",
    "于艳.md",
    "刘胡权.md",
    "孟庆任.md",
    "王敬波.md",
    "田涛.md",
    "闵凡祥.md",
    "陈大文.md",
    "王俊宏.md",
    "王婉旎.md",
    "王承玥.md",
    "王雪飞.md",
    "郎艳.md",
    "郑端午.md",
    "雷逸.md",
    "麦克霍恩.md",
    "张葳.md",
    "张尚达.md",
    "杨学建.md",
    "杨西云.md",
    "柳罐斗.md",
    "桂生.md",
    "赵文君.md",
    "蔡士魁.md",
    "许晨.md",
    "许斌.md",
    "杨振宁.md",
    "马晨明.md",
    "高国希.md",
}

NON_AUTHENTIC_MARKER = (
    "> **说明**：人物真实性存疑，可能为虚构、误传或同名混淆，"
    "不将其视为历史人物，也不应生成真实足迹地图。\n\n"
)


LOCATION_SECTION_RE = re.compile(r"^##\s+[一二三四五六七八九十]*、?\s*人生历程与重要地点（按时间顺序）\s*$", re.M)
TIMELINE_SECTION_RE = re.compile(r"^##\s+[一二三四五六七八九十]*、?\s*生平时间线\s*$", re.M)
COORDS_SECTION_RE = re.compile(r"^##\s+(?:[一二三四五六七八九十]+、\s*)?地点坐标(?:（[^）]*）)?\s*$", re.M)
LOCATION_HEADING_RE = re.compile(r"^###\s+[🟢📍🔴]\s*(.+)$")
FIELD_RE = re.compile(r"^- \*\*(时间|公元纪年|事件|事迹|经过)\*\*：\s*(.+?)\s*$")
POSITION_RE = re.compile(r"^- \*\*(?:位置|地点)\*\*：\s*(.+?)\s*$")
AMBIGUOUS_GEO_TERMS = (
    "待考",
    "不详",
    "存疑",
    "说法不一",
    "附近",
    "周边",
    "一带",
    "沿线",
    "流域",
    "地区",
    "等地",
    "诸地",
    "各地",
    "具体区域待考",
)
FOREIGN_GEO_TERMS = (
    "美国",
    "英国",
    "德国",
    "法国",
    "瑞士",
    "奥地利",
    "捷克",
    "荷兰",
    "俄罗斯",
    "日本",
    "韩国",
    "朝鲜",
    "印度",
    "尼泊尔",
    "菲律宾",
    "澳大利亚",
    "委内瑞拉",
    "哥伦比亚",
    "瑞典",
    "波兰",
    "蒙古国",
)
DOMESTIC_GEO_HINTS = (
    "省",
    "市",
    "区",
    "县",
    "州",
    "盟",
    "旗",
    "自治区",
    "特别行政区",
    "北京",
    "上海",
    "天津",
    "重庆",
    "香港",
    "澳门",
)


def _insert_non_authentic_marker(text: str) -> str:
    if "可能为虚构、误传或同名混淆" in text[:4000]:
        return text
    match = re.match(r"^(#\s+.+\n+)", text)
    if not match:
        return NON_AUTHENTIC_MARKER + text
    return text[: match.end()] + NON_AUTHENTIC_MARKER + text[match.end() :]


def _normalize_headings(text: str) -> str:
    # Normalize parser-sensitive section headings.
    text = re.sub(
        r"^##\s+([一二三四五六七八九十]+、\s*)?人生历程与重要地点（按时间顺序[^）)]*[）)]\s*$",
        lambda m: f"## {m.group(1) or ''}人生历程与重要地点（按时间顺序）",
        text,
        flags=re.M,
    )
    text = re.sub(
        r"^##\s+([一二三四五六七八九十]+、\s*)?人生历程与重要地点\s*$",
        lambda m: f"## {m.group(1) or ''}人生历程与重要地点（按时间顺序）",
        text,
        flags=re.M,
    )
    text = re.sub(
        r"^##\s+([一二三四五六七八九十]+、\s*)?生平时间线[^\n]*$",
        lambda m: f"## {m.group(1) or ''}生平时间线",
        text,
        flags=re.M,
    )
    return text


def _normalize_title(path: Path, text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    first = lines[0].strip()
    if not first.startswith("# "):
        return text
    title = first[2:].strip()
    title_name = re.split(r"[（(【[]", title, maxsplit=1)[0].strip()
    if title == "人物 生平传记与足迹":
        lines[0] = f"# {path.stem}"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if title.endswith(" 生平传记与足迹"):
        lines[0] = f"# {title[:-8].strip()}"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if path.name in NON_AUTHENTIC_FILES and (title == "未知人物（待考）" or title_name != path.stem):
        lines[0] = f"# {path.stem}（内容待核）"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text


def _normalize_location_headings(text: str) -> str:
    replacements = (
        (r"^###\s+(?:\d+\.\s*)?出生地：", "### 🟢 出生地："),
        (r"^###\s+(?:\d+\.\s*)?重要地点：", "### 📍 重要地点："),
        (r"^###\s+(?:\d+\.\s*)?去世地：", "### 🔴 去世地："),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.M)
    return text


def _extract_location_entries(text: str) -> list[tuple[str, str, str]]:
    match = LOCATION_SECTION_RE.search(text)
    if not match:
        return []
    start = match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    section = tail[: next_section.start()] if next_section else tail
    entries: list[tuple[str, str, str]] = []
    current_name = ""
    current_time = ""
    current_event = ""
    for raw in section.splitlines():
        heading = LOCATION_HEADING_RE.match(raw.strip())
        if heading:
            if current_name:
                entries.append((current_name, current_time or "不详", current_event or "见地点小节"))
            current_name = _normalize_location_label(heading.group(1).strip())
            current_time = ""
            current_event = ""
            continue
        field = FIELD_RE.match(raw.strip())
        if not field:
            continue
        key, value = field.groups()
        value = value.strip()
        if key in {"时间", "公元纪年"} and not current_time:
            current_time = value
        if key in {"事件", "事迹", "经过"} and not current_event:
            current_event = value
    if current_name:
        entries.append((current_name, current_time or "不详", current_event or "见地点小节"))
    return entries


def _extract_location_names(text: str) -> list[str]:
    return [name for name, _when, _event in _extract_location_entries(text)]


def _extract_location_points(text: str) -> list[tuple[str, str]]:
    match = LOCATION_SECTION_RE.search(text)
    if not match:
        return []
    start = match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    section = tail[: next_section.start()] if next_section else tail
    points: list[tuple[str, str]] = []
    current_name = ""
    current_position = ""
    for raw in section.splitlines():
        heading = LOCATION_HEADING_RE.match(raw.strip())
        if heading:
            if current_name and current_position:
                points.append((current_name, current_position))
            current_name = _normalize_location_label(heading.group(1).strip())
            current_position = ""
            continue
        position = POSITION_RE.match(raw.strip())
        if position:
            current_position = position.group(1).strip()
    if current_name and current_position:
        points.append((current_name, current_position))
    return points


def _normalize_place_match_key(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"[（(].*?[）)]", "", raw)
    raw = re.sub(r"^(今|现|今称|现称)\s*", "", raw)
    raw = re.sub(r"[，,。.;；:：、】【\\[\\]{}<>《》\"'“”‘’·•/\\\\|-]+", "", raw)
    raw = re.sub(r"(省|市|县|区|州|郡|府|道|路|镇|乡|村|国)$", "", raw)
    raw = re.sub(r"\s+", "", raw)
    return raw.strip()


def _location_alias_tokens(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    tokens: list[str] = []
    for candidate in [raw, re.sub(r"[（(].*?[）)]", "", raw).strip()]:
        candidate = str(candidate or "").strip()
        if candidate and candidate not in tokens:
            tokens.append(candidate)
    for inner in re.findall(r"[（(]([^）)]+)[）)]", raw):
        for part in re.split(r"[、，,；;/]|或", inner):
            clean = str(part or "").strip()
            if clean and clean not in tokens:
                tokens.append(clean)
    return tokens


def _is_placeholder_place(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(token in raw for token in ("出生地", "去世地", "重要地点", "存疑", "说法不一"))


def _extract_year_value(text: str) -> int | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = re.search(r"(公元前|前)?\s*(\d{1,4})", raw)
    if not match:
        return None
    value = int(match.group(2))
    if match.group(1):
        return -value
    return value


def _extract_year_range(text: str) -> tuple[int, int] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    values: list[int] = []
    for match in re.finditer(r"(公元前|前)?\s*(\d{1,4})", raw):
        value = int(match.group(2))
        if match.group(1):
            value = -value
        values.append(value)
    if not values:
        return None
    return min(values), max(values)


def _extract_ancient_modern_from_position(name: str, position: str) -> tuple[str, str]:
    label = _normalize_location_label(name)
    if any(token in label for token in ("出生地", "去世地", "重要地点", "存疑", "说法不一")):
        label = ""
    raw_position = str(position or "").strip()
    modern = ""
    modern_match = re.search(r"[（(]\s*今\s*([^）)]+)[）)]", raw_position)
    if modern_match:
        modern_candidate = modern_match.group(1).strip()
        if _is_safe_geocode_candidate(modern_candidate):
            modern = _clean_geocode_candidate(modern_candidate)
    if not modern:
        modern_candidate = _clean_geocode_candidate(raw_position)
        if _is_safe_geocode_candidate(modern_candidate):
            modern = modern_candidate
    if not label:
        ancient_candidate = re.sub(r"[（(]\s*今\s*[^）)]+[）)]", "", raw_position).strip()
        ancient_candidate = re.sub(r"^(说法不一[，,、；;]\s*)", "", ancient_candidate)
        ancient_candidate = re.sub(r"^(?:一说|又说|或说|一作|一为)\s*", "", ancient_candidate)
        for sep in ("，一说", ",一说", "；", ";", "，", ",", "、", "或", "/"):
            if sep in ancient_candidate:
                ancient_candidate = ancient_candidate.split(sep, 1)[0].strip()
                break
        ancient_candidate = re.sub(r"^(?:地点|位置)[:：]\s*", "", ancient_candidate)
        ancient_candidate = re.sub(r"^(?:说法不一|存疑)\s*", "", ancient_candidate).strip("：: ，,")
        if ancient_candidate:
            label = ancient_candidate
    return label, modern


def _extract_location_point_records(text: str) -> list[dict[str, object]]:
    match = LOCATION_SECTION_RE.search(text)
    if not match:
        return []
    start = match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    section = tail[: next_section.start()] if next_section else tail
    records: list[dict[str, object]] = []
    current_label = ""
    current_name = ""
    current_time = ""
    current_event = ""
    current_position = ""
    for raw in section.splitlines():
        stripped = raw.strip()
        heading = LOCATION_HEADING_RE.match(stripped)
        if heading:
            if current_name:
                ancient, modern = _extract_ancient_modern_from_position(current_name, current_position)
                records.append(
                    {
                        "label": current_label,
                        "name": current_name,
                        "time": current_time,
                        "event": current_event,
                        "position": current_position,
                        "ancient": ancient,
                        "modern": modern,
                        "year_range": _extract_year_range(current_time),
                    }
                )
            current_label = heading.group(1).strip()
            current_name = _normalize_location_label(current_label)
            current_time = ""
            current_event = ""
            current_position = ""
            continue
        position = POSITION_RE.match(stripped)
        if position and not current_position:
            current_position = position.group(1).strip()
            continue
        field = FIELD_RE.match(stripped)
        if not field:
            continue
        key, value = field.groups()
        value = value.strip()
        if key in {"时间", "公元纪年"} and not current_time:
            current_time = value
        elif key in {"事件", "事迹", "经过"} and not current_event:
            current_event = value
    if current_name:
        ancient, modern = _extract_ancient_modern_from_position(current_name, current_position)
        records.append(
            {
                "label": current_label,
                "name": current_name,
                "time": current_time,
                "event": current_event,
                "position": current_position,
                "ancient": ancient,
                "modern": modern,
                "year_range": _extract_year_range(current_time),
            }
        )
    return records


def _score_timeline_location_match(
    year_text: str,
    event_text: str,
    point: dict[str, object],
) -> tuple[int, bool]:
    score = 0
    explicit = False
    raw_event = str(event_text or "").strip()
    normalized_event = _normalize_place_match_key(raw_event)
    for candidate in (
        point.get("name"),
        point.get("ancient"),
        point.get("modern"),
        point.get("position"),
    ):
        for text in _location_alias_tokens(str(candidate or "").strip()):
            if len(text) >= 2 and text in raw_event:
                score = max(score, 8)
                explicit = True
                break
            normalized_candidate = _normalize_place_match_key(text)
            if normalized_candidate and len(normalized_candidate) >= 2 and normalized_candidate in normalized_event:
                score = max(score, 6)
                explicit = True
                break
        if explicit:
            break
    year_value = _extract_year_value(year_text)
    year_range = point.get("year_range")
    if year_value is not None and isinstance(year_range, tuple) and len(year_range) == 2:
        start, end = year_range
        if start <= year_value <= end:
            score += 4 if start == end == year_value else 3
    label = str(point.get("label") or "")
    if ("出生地" in label) and any(token in raw_event for token in ("生于", "出生")):
        score += 3
    if ("去世地" in label) and any(token in raw_event for token in ("去世", "病逝", "逝于", "卒于")):
        score += 3
    return score, explicit


def _fill_timeline_locations_from_sections(text: str) -> str:
    points = _extract_location_point_records(text)
    if not points:
        return text
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if not timeline_match:
        return text
    start = timeline_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    lines = body.splitlines()
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return text
    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    if len(header) < 4 or "古称" not in header[1] or "现称" not in header[2] or "事件" not in header[3]:
        return text

    rebuilt: list[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            rebuilt.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            rebuilt.append(line)
            continue
        if cells == header:
            rebuilt.append(line)
            continue
        if len(cells) < 4:
            rebuilt.append(line)
            continue
        ancient = cells[1]
        modern = cells[2]
        if ancient and modern and not _is_placeholder_place(ancient):
            rebuilt.append(line)
            continue
        scored: list[tuple[int, bool, int, dict[str, object]]] = []
        for idx, point in enumerate(points):
            score, explicit = _score_timeline_location_match(cells[0], cells[3], point)
            if score > 0:
                scored.append((score, explicit, idx, point))
        scored.sort(key=lambda item: (item[0], item[1], -item[2]), reverse=True)
        if not scored:
            rebuilt.append(line)
            continue
        best_score, best_explicit, _best_idx, best_point = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else -1
        if best_score < 8 and not (best_explicit and best_score >= 6) and not (best_score >= 7 and second_score < best_score):
            rebuilt.append(line)
            continue
        candidate_ancient = str(best_point.get("ancient") or "").strip()
        if (not ancient) or _is_placeholder_place(ancient):
            new_ancient = candidate_ancient or ancient
        else:
            new_ancient = ancient
        new_modern = modern or str(best_point.get("modern") or "").strip()
        if not new_ancient and not new_modern:
            rebuilt.append(line)
            continue
        updated = [cells[0], new_ancient, new_modern, cells[3]]
        rebuilt.append(f"| {updated[0]} | {updated[1]} | {updated[2]} | {updated[3]} |")
        changed = True
    if not changed:
        return text
    return text[:start] + "\n" + "\n".join(rebuilt).strip("\n") + "\n\n" + text[end:]


def _clean_geocode_candidate(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^今", "", raw)
    modern_match = re.search(r"[（(]\s*今\s*([^）)]+)[）)]", raw)
    if modern_match:
        raw = modern_match.group(1).strip()
    else:
        raw = re.sub(r"\b今(?:称)?\s*([^\s，。；;、/]+)", r"\1", raw)
    raw = re.sub(r"[（(]\s*具体区域待考\s*[）)]", "", raw)
    raw = re.sub(r"[（(].*?[）)]", "", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip(" ，。；;")


def _normalize_location_label(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^(?:出生地|重要地点|去世地)\s*[:：]\s*", "", raw)
    return raw.strip()


def _is_safe_geocode_candidate(text: str) -> bool:
    raw = _clean_geocode_candidate(text)
    if not raw:
        return False
    if any(token in raw for token in AMBIGUOUS_GEO_TERMS):
        return False
    if "、" in raw or " / " in raw or "/" in raw:
        return False
    return True


def _looks_domestic_candidate(text: str) -> bool:
    raw = _clean_geocode_candidate(text)
    if not raw:
        return False
    if re.search(r"[A-Za-z]", raw):
        return False
    if any(token in raw for token in FOREIGN_GEO_TERMS):
        return False
    return any(token in raw for token in DOMESTIC_GEO_HINTS)


def _build_coords_table(rows: list[tuple[str, str, float, float]]) -> str:
    rebuilt = [
        "| 现称 | 现代搜索地名 | 纬度 | 经度 |",
        "| --- | --- | --- | --- |",
    ]
    for name, search, lat, lon in rows:
        rebuilt.append(f"| {name} | {search} | {lat:.6f} | {lon:.6f} |")
    return "\n".join(rebuilt)


def _ensure_coords_section(text: str) -> str:
    if COORDS_SECTION_RE.search(text):
        return text
    source_rows = _extract_location_points(text)
    if not source_rows:
        return text
    if not all(_looks_domestic_candidate(search or name) for name, search in source_rows):
        return text
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if not timeline_match:
        return text
    start = timeline_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    insert_at = start + next_section.start() if next_section else len(text)
    insertion = "\n## 地点坐标\n"
    return text[:insert_at].rstrip() + "\n\n" + insertion + text[insert_at:]


def _populate_coords_table(text: str) -> str:
    section_match = COORDS_SECTION_RE.search(text)
    if not section_match:
        return text
    start = section_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    table_lines = [line for line in body.splitlines() if line.strip().startswith("|")]

    source_rows: list[tuple[str, str]] = []
    if len(table_lines) >= 2:
        header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
        if any("纬度" in cell for cell in header) and any("经度" in cell for cell in header):
            return text
        for line in table_lines[2:]:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not cells:
                continue
            name = cells[0]
            search = cells[0]
            if len(cells) >= 2 and any(token in header[1] for token in ("现代", "行政区")):
                search = cells[1]
            source_rows.append((name, search))
    if not source_rows:
        source_rows = _extract_location_points(text)
    if not source_rows:
        return text

    resolved_rows: list[tuple[str, str, float, float]] = []
    for name, raw_search in source_rows:
        search = _clean_geocode_candidate(raw_search or name)
        if not _is_safe_geocode_candidate(search):
            return text
        coord = mc.geocode_city(search)
        if not coord:
            fallback = _clean_geocode_candidate(name)
            if fallback != search and _is_safe_geocode_candidate(fallback):
                coord = mc.geocode_city(fallback)
        if not coord:
            return text
        resolved_rows.append((name, search, float(coord[0]), float(coord[1])))

    new_body = "\n" + _build_coords_table(resolved_rows) + "\n"
    return text[:start] + new_body + text[end:]


def _align_coords_table_with_location_headings(text: str) -> str:
    names = _extract_location_names(text)
    if not names:
        return text
    section_match = COORDS_SECTION_RE.search(text)
    if not section_match:
        return text
    start = section_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    table_lines = [line for line in body.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        return text
    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    legacy_three_col = len(header) == 3 and "纬度" in header[1] and "经度" in header[2]
    standard_four_col = len(header) == 4 and "纬度" in header[2] and "经度" in header[3]
    if not legacy_three_col and not standard_four_col:
        return text
    rows: list[list[str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        expected_len = 3 if legacy_three_col else 4
        if len(cells) != expected_len:
            return text
        rows.append(cells)
    if len(rows) != len(names):
        return text
    rebuilt = [
        "| 现称 | 现代搜索地名 | 纬度 | 经度 |",
        "| --- | --- | --- | --- |",
    ]
    for name, row in zip(names, rows):
        if legacy_three_col:
            rebuilt.append(f"| {name} | {row[0]} | {row[1]} | {row[2]} |")
        else:
            rebuilt.append(f"| {name} | {row[1]} | {row[2]} | {row[3]} |")
    new_body = "\n" + "\n".join(rebuilt) + "\n"
    return text[:start] + new_body + text[end:]


def _build_timeline_table(entries: list[tuple[str, str, str]]) -> str:
    lines = ["| 年份 | 阶段 | 关键事件 |", "| --- | --- | --- |"]
    for name, when, event in entries:
        label = event.replace("|", " / ")
        lines.append(f"| {when} | {name} | {label} |")
    return "\n".join(lines)


def _ensure_timeline_section(text: str) -> str:
    entries = _extract_location_entries(text)
    if not entries:
        return text
    table = _build_timeline_table(entries)
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if timeline_match:
        start = timeline_match.end()
        tail = text[start:]
        next_section = re.search(r"^##\s+", tail, re.M)
        end = start + next_section.start() if next_section else len(text)
        body = text[start:end]
        if "|" in body:
            return text
        replacement = "\n" + table + "\n\n"
        return text[:start] + replacement + text[end:]
    location_match = LOCATION_SECTION_RE.search(text)
    if not location_match:
        return text
    insertion = "\n\n## 生平时间线\n" + table + "\n"
    coords_match = re.search(r"^##\s+地点坐标\s*$", text, re.M)
    if coords_match:
        return text[: coords_match.start()] + insertion + "\n" + text[coords_match.start() :]
    return text.rstrip() + insertion + "\n"


def _upgrade_two_column_timeline(text: str) -> str:
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if not timeline_match:
        return text
    start = timeline_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    lines = body.splitlines()
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return text
    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    if len(header) != 2 or "年份" not in header[0] or ("事件" not in header[1] and "关键事件" not in header[1]):
        return text
    rebuilt: list[str] = []
    converted = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            rebuilt.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == 2:
            if not converted:
                rebuilt.append("| 年份 | 阶段 | 关键事件 |")
                converted = True
            elif re.fullmatch(r":?-{3,}:?", cells[0]) and re.fullmatch(r":?-{3,}:?", cells[1]):
                rebuilt.append("| --- | --- | --- |")
            else:
                rebuilt.append(f"| {cells[0]} | 不详 | {cells[1]} |")
            continue
        rebuilt.append(line)
    if not converted:
        return text
    return text[:start] + "\n" + "\n".join(rebuilt).strip("\n") + "\n\n" + text[end:]


def _upgrade_legacy_three_column_timeline(text: str) -> str:
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if not timeline_match:
        return text
    start = timeline_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    lines = body.splitlines()
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return text

    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    if len(header) != 3 or "年份" not in header[0]:
        return text
    if any("古称" in cell or "现称" in cell for cell in header):
        return text
    if not any("事件" in cell for cell in header):
        return text

    middle_label = header[1] or "补充信息"
    rebuilt: list[str] = []
    converted = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            rebuilt.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == 3:
            if not converted:
                rebuilt.append("| 年份 | 古称 | 现称 | 事件 |")
                converted = True
            elif all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                rebuilt.append("| --- | --- | --- | --- |")
            else:
                year = cells[0]
                context = cells[1]
                event = cells[2]
                if context and context not in {"—", "-"}:
                    event = f"（{middle_label}：{context}）{event}" if event else f"{middle_label}：{context}"
                rebuilt.append(f"| {year} |  |  | {event} |")
            continue
        rebuilt.append(line)
    if not converted:
        return text
    return text[:start] + "\n" + "\n".join(rebuilt).strip("\n") + "\n\n" + text[end:]


def _upgrade_single_column_timeline(text: str) -> str:
    timeline_match = TIMELINE_SECTION_RE.search(text)
    if not timeline_match:
        return text
    start = timeline_match.end()
    tail = text[start:]
    next_section = re.search(r"^##\s+", tail, re.M)
    end = start + next_section.start() if next_section else len(text)
    body = text[start:end]
    lines = body.splitlines()
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return text

    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    if len(header) != 1 or not any("事件" in cell for cell in header):
        return text

    rebuilt: list[str] = []
    converted = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            rebuilt.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == 1:
            if not converted:
                rebuilt.append("| 年份 | 古称 | 现称 | 事件 |")
                converted = True
            elif re.fullmatch(r":?-{3,}:?", cells[0]):
                rebuilt.append("| --- | --- | --- | --- |")
            else:
                rebuilt.append(f"|  |  |  | {cells[0]} |")
            continue
        rebuilt.append(line)
    if not converted:
        return text
    return text[:start] + "\n" + "\n".join(rebuilt).strip("\n") + "\n\n" + text[end:]


def fix_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = original
    updated = _normalize_title(path, updated)
    updated = _normalize_headings(updated)
    updated = _normalize_location_headings(updated)
    updated = _ensure_timeline_section(updated)
    updated = _upgrade_two_column_timeline(updated)
    updated = _upgrade_legacy_three_column_timeline(updated)
    updated = _upgrade_single_column_timeline(updated)
    updated = _fill_timeline_locations_from_sections(updated)
    updated = _ensure_coords_section(updated)
    updated = _populate_coords_table(updated)
    updated = _align_coords_table_with_location_headings(updated)
    if path.name in NON_AUTHENTIC_FILES:
        updated = _insert_non_authentic_marker(updated)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize StoryMap markdown corpus for map generation.")
    parser.add_argument(
        "--story-dir",
        default="storymap/examples/story",
        help="Directory containing story markdown files.",
    )
    args = parser.parse_args()

    story_dir = Path(args.story_dir).resolve()
    changed = 0
    for path in sorted(story_dir.glob("*.md")):
        if fix_file(path):
            changed += 1
            print(path.name)
    print(f"changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
