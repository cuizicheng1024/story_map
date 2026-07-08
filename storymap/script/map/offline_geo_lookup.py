from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_DATA_DIR = REPO_ROOT / "tools" / "build" / "data"
ANCIENT_CSV = BUILD_DATA_DIR / "ancient_to_modern.csv"
COORDS_JSON = BUILD_DATA_DIR / "city_coords.json"

UNRESOLVABLE_PLACES = frozenset({
    "不详",
    "待补充",
    "存疑",
    "说法不一",
    "存疑/说法不一/待考",
    "待考证",
    "暂无可用",
    "unknown",
})

UNRESOLVABLE_PERSON_PLACES: set[tuple[str, str]] = {
    ("孙武", "不详"), ("张仲景", "不详"), ("张三丰", "待补充"),
    ("韩信", "待补充"), ("莫扎特", "待补充"), ("西施", "存疑"),
    ("赵师秀", "说法不一"), ("陈韪", "不详"), ("隋炀帝", "存疑/说法不一/待考"),
}

EMPTY_LOCATIONS_FALLBACK: dict[str, list[dict]] = {
    "苏颂": [
        {"name": "同安（出生地）", "lat": 24.7233, "lng": 118.1577},
        {"name": "开封（仕途）", "lat": 34.7975, "lng": 114.3076},
        {"name": "杭州（晚年）", "lat": 30.2741, "lng": 120.1551},
    ],
    "张三丰": [
        {"name": "武当山（修道）", "lat": 32.4000, "lng": 111.0000},
        {"name": "辽东懿州（出生地，存疑）", "lat": 42.0000, "lng": 121.7000},
    ],
    "莫扎特": [
        {"name": "萨尔茨堡（出生地）", "lat": 47.8000, "lng": 13.0500},
        {"name": "维也纳（逝世地）", "lat": 48.2082, "lng": 16.3738},
    ],
    "韩信": [
        {"name": "淮阴（出生地）", "lat": 33.5000, "lng": 119.1000},
        {"name": "汉中（拜将）", "lat": 33.0700, "lng": 107.0300},
        {"name": "井陉（背水一战）", "lat": 38.0300, "lng": 114.1400},
        {"name": "垓下（十面埋伏）", "lat": 33.5200, "lng": 117.5500},
        {"name": "长安（遇害地）", "lat": 34.3416, "lng": 108.9398},
    ],
}


def load_ancient_mappings(csv_path: Path | None = None, *, required: bool = False) -> dict[tuple[str, str], str]:
    path = csv_path or ANCIENT_CSV
    if not path.exists():
        if required:
            raise FileNotFoundError(f"古地名映射文件不存在: {path}")
        return {}
    result: dict[tuple[str, str], str] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["person"].strip(), row["ancient_name"].strip())
            result[key] = row["modern_name"].strip()
    return result


def load_city_coords(json_path: Path | None = None, *, required: bool = False) -> dict[str, tuple[float, float]]:
    path = json_path or COORDS_JSON
    if not path.exists():
        if required:
            raise FileNotFoundError(f"城市坐标文件不存在: {path}")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: (float(v[0]), float(v[1])) for k, v in raw.items()}


class GeoLookup:
    def __init__(self) -> None:
        self._ancient_map = load_ancient_mappings()
        self._city_coords = load_city_coords()

    def is_unresolvable(self, place: str) -> bool:
        return place.strip() in UNRESOLVABLE_PLACES

    def resolve(self, place: str, *, person: str = "") -> Optional[dict]:
        place = place.strip()
        if not place or place in UNRESOLVABLE_PLACES:
            return None

        modern = ""
        if person:
            modern = self._ancient_map.get((person, place), "")
            if not modern:
                for (p, ancient), mapped in self._ancient_map.items():
                    if p == person and place in ancient:
                        modern = mapped
                        break

        if not modern:
            for (_, ancient), mapped in self._ancient_map.items():
                if ancient == place or place in ancient:
                    modern = mapped
                    break

        if not modern:
            return None

        coords = self._city_coords.get(modern)
        if coords is None:
            return {"modern_name": modern, "lat": None, "lng": None}
        return {"modern_name": modern, "lat": coords[0], "lng": coords[1]}

    def empty_locations_fallback(self, person: str) -> Optional[list[dict]]:
        return EMPTY_LOCATIONS_FALLBACK.get(person)


_geo_lookup: Optional[GeoLookup] = None


def get_geo_lookup() -> GeoLookup:
    global _geo_lookup
    if _geo_lookup is None:
        _geo_lookup = GeoLookup()
    return _geo_lookup


__all__ = [
    "ANCIENT_CSV",
    "COORDS_JSON",
    "EMPTY_LOCATIONS_FALLBACK",
    "GeoLookup",
    "UNRESOLVABLE_PERSON_PLACES",
    "UNRESOLVABLE_PLACES",
    "get_geo_lookup",
    "load_ancient_mappings",
    "load_city_coords",
]
