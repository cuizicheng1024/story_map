from __future__ import annotations

import re
from typing import List, Tuple


_TABLE_SEPARATOR_RE = re.compile(r"^\|\s*-{3,}\s*\|")
_PAREN_CONTENT_RE = re.compile(r"[（(].*?[)）]")


def clean_place_name(text: object) -> str:
    if not isinstance(text, str):
        return ""
    text = _PAREN_CONTENT_RE.sub("", text)
    return text.strip()


def extract_places_in_order(md: object) -> List[str]:
    if not isinstance(md, str):
        return []
    lines = md.splitlines()
    in_loc = False
    table_started = False
    display_idx = None
    search_idx = None
    places: List[str] = []
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            if title.startswith("年份") or "生平时间线" in title:
                in_loc = True
                table_started = False
                display_idx = None
                search_idx = None
                continue
            in_loc = False
        if not in_loc:
            continue
        if line.strip().startswith("|") and not table_started:
            table_started = True
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            for idx, cell in enumerate(header_cells):
                if search_idx is None and "现代搜索地名" in cell:
                    search_idx = idx
                if display_idx is None and ("现称" in cell or "地点" in cell):
                    display_idx = idx
            continue
        if not table_started:
            continue
        stripped = line.strip()
        if _TABLE_SEPARATOR_RE.match(stripped):
            continue
        if not stripped.startswith("|"):
            break
        if search_idx is None and display_idx is None:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        cell = ""
        if search_idx is not None and search_idx < len(cells):
            cell = cells[search_idx]
        if not cell and display_idx is not None and display_idx < len(cells):
            cell = cells[display_idx]
        if "：" in cell:
            cell = cell.split("：", 1)[-1].strip()
        clean = clean_place_name(cell)
        if clean and clean != "—":
            places.append(clean)
    return list(dict.fromkeys(places)) if places else []


def strip_auto_coords_section(md: object) -> str:
    if not isinstance(md, str):
        return ""
    if "地点坐标（自动地理编码）" not in md:
        return md
    lines = md.splitlines()
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            if "地点坐标（自动地理编码）" in title:
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            out.append(line)
    while len(out) >= 2 and (not out[-1].strip()) and (not out[-2].strip()):
        out.pop()
    return "\n".join(out)


def extract_auto_coords_section_places(md: object) -> List[str]:
    if not isinstance(md, str) or "地点坐标（自动地理编码）" not in md:
        return []
    lines = md.splitlines()
    in_section = False
    header_seen = False
    places: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            in_section = "地点坐标（自动地理编码）" in title
            header_seen = False
            continue
        if not in_section:
            continue
        if stripped.startswith("|") and not header_seen:
            header_seen = True
            continue
        if not header_seen:
            continue
        compact = stripped.replace("|", "").replace(":", "").replace("-", "").strip()
        if not compact:
            continue
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5 or not cells[4]:
            continue
        try:
            float(cells[2])
            float(cells[3])
        except Exception:
            continue
        name = cells[0]
        if name:
            places.append(name)
    return places


def extract_coords_table_rows(md: object, *, section_keyword: str = "地点坐标") -> List[Tuple[str, str, float, float, str]]:
    if not isinstance(md, str) or section_keyword not in md:
        return []
    lines = md.splitlines()
    in_section = False
    header_seen = False
    rows: List[Tuple[str, str, float, float, str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            in_section = section_keyword in title
            header_seen = False
            continue
        if not in_section:
            continue
        if stripped.startswith("|") and not header_seen:
            header_seen = True
            continue
        if not header_seen:
            continue
        compact = stripped.replace("|", "").replace(":", "").replace("-", "").strip()
        if not compact:
            continue
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        parsed = _parse_coord_table_row(cells)
        if parsed:
            rows.append(parsed)
    return rows


def extract_coord_pairs(md: object, *, section_keyword: str = "地点坐标") -> List[Tuple[float, float]]:
    return [(lat, lon) for _, _, lat, lon, _ in extract_coords_table_rows(md, section_keyword=section_keyword)]


def _parse_coord_table_row(cells: List[str]) -> Tuple[str, str, float, float, str] | None:
    if len(cells) >= 5:
        name = cells[0]
        search_name = cells[1]
        lat_raw = cells[2]
        lon_raw = cells[3]
        coord_system = cells[4]
    elif len(cells) >= 4:
        name = cells[0]
        search_name = cells[0]
        lat_raw = cells[2]
        lon_raw = cells[3]
        coord_system = ""
    elif len(cells) >= 3:
        name = cells[0]
        search_name = cells[0]
        lat_raw = cells[1]
        lon_raw = cells[2]
        coord_system = ""
    else:
        return None
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except Exception:
        return None
    if not coord_system and len(cells) >= 5:
        coord_system = cells[4]
    return name, search_name, lat, lon, coord_system
