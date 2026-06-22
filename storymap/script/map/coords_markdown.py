from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

from . import coords_markdown_sections as coords_markdown_section_utils


def extract_places_in_order(md: object) -> List[str]:
    return coords_markdown_section_utils.extract_places_in_order(md)


def append_coords_section(
    md: object,
    *,
    geocode_fn: Callable[[str], Optional[Tuple[float, float]]],
) -> str:
    if not isinstance(md, str):
        return ""
    timeline_places = extract_places_in_order(md)
    existing_auto_places = coords_markdown_section_utils.extract_auto_coords_section_places(md)
    if existing_auto_places and timeline_places and existing_auto_places == timeline_places:
        return md
    base_md = coords_markdown_section_utils.strip_auto_coords_section(md)
    changed = base_md != md
    lines = base_md.splitlines()
    coords: Dict[str, Tuple[float, float]] = {}
    places = timeline_places or extract_places_in_order(base_md)
    if not places:
        return base_md if changed else md
    max_workers = min(8, max(1, len(places)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(geocode_fn, p): p for p in places}
        for future in as_completed(future_map):
            place = future_map[future]
            try:
                coord = future.result()
            except Exception:
                coord = None
            if coord:
                coords[place] = coord
    if not coords:
        return base_md if changed else md
    section = [
        "",
        "## 地点坐标（自动地理编码）",
        "| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in places:
        if p in coords:
            lat, lon = coords[p]
            section.append(f"| {p} | {p} | {lat:.6f} | {lon:.6f} | WGS84 |")
    return "\n".join(lines + section)


def compute_total_distance_km(md: object) -> Optional[float]:
    if not isinstance(md, str):
        return None
    coords = coords_markdown_section_utils.extract_coord_pairs(md, section_keyword="地点坐标")
    if len(coords) < 2:
        return None
    total = 0.0
    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]
        total += _haversine(lat1, lon1, lat2, lon2)
    return total


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def insert_distance_intro(md: object, distance_km: float) -> str:
    if not isinstance(md, str):
        return ""
    lines = md.splitlines()
    out: List[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.strip().startswith("## 二、人生足迹地图说明"):
            continue
        if not inserted and line.strip().startswith("- 🌟 **重要节点数量**"):
            out.append(f"- 🚶 **总行程估算**：约 {distance_km:.0f} 公里")
            inserted = True
    return "\n".join(out)


__all__ = [
    "append_coords_section",
    "compute_total_distance_km",
    "extract_places_in_order",
    "insert_distance_intro",
]
