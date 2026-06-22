from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from ..core import parsers as parser_utils


Coord = Tuple[float, float]
_SPECULATIVE_LOCATION_PATTERNS = (
    r"推断",
    r"存疑",
    r"待考",
    r"说法不一",
    r"史料未载",
    r"不可考",
    r"古称不详",
    r"地点不详",
    r"某地",
    r"周边区域",
    r"可能",
)


def loose_place_key(text: str) -> str:
    cleaned = parser_utils._pick_geocode_name(str(text or ""))
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（(].*?[）)]", "", cleaned)
    cleaned = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", cleaned)
    for token in ("风景区", "景区", "古战场", "旧址", "遗址", "故居", "博物馆"):
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"[省市区县州郡府镇乡村旗盟]", "", cleaned)
    return cleaned.strip()


def loose_coord_lookup(coords_cache: Dict[str, Coord], candidates: List[str]) -> Optional[Coord]:
    if not coords_cache:
        return None
    loose_candidates = [loose_place_key(candidate) for candidate in candidates if str(candidate or "").strip()]
    loose_candidates = [candidate for candidate in loose_candidates if candidate]
    if not loose_candidates:
        return None
    scored: List[Tuple[int, str]] = []
    for raw_key in coords_cache.keys():
        key = str(raw_key or "").strip()
        if not key:
            continue
        loose_key = loose_place_key(key)
        if not loose_key:
            continue
        for candidate in loose_candidates:
            if loose_key in candidate or candidate in loose_key:
                scored.append((len(loose_key), key))
                break
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return coords_cache.get(scored[0][1])


def coord_group_key(lat: object, lng: object) -> str:
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except Exception:
        return ""
    if not (-90 <= lat_value <= 90 and -180 <= lng_value <= 180):
        return ""
    return f"{lat_value:.4f},{lng_value:.4f}"


def is_speculative_location_item(item: Dict[str, object]) -> bool:
    text = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("ancientName") or ""),
            str(item.get("modernName") or ""),
            str(item.get("event") or ""),
            str(item.get("significance") or ""),
            str(item.get("time") or ""),
        ]
    ).strip()
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in _SPECULATIVE_LOCATION_PATTERNS)


def choose_primary_location(items: List[Dict[str, object]], *, extract_works: Callable[[str], List[str]]) -> Dict[str, object]:
    def score(item: Dict[str, object]) -> Tuple[int, int, int]:
        text = " ".join(
            [
                str(item.get("event") or ""),
                str(item.get("significance") or ""),
                str(item.get("duration") or ""),
            ]
        ).strip()
        return (
            1 if str(item.get("duration") or "").strip() else 0,
            len(extract_works(text)),
            len(text),
        )

    return max(items, key=score)


def merge_location_cluster(items: List[Dict[str, object]], *, extract_works: Callable[[str], List[str]]) -> Dict[str, object]:
    base = dict(choose_primary_location(items, extract_works=extract_works))

    def merge_text(field: str) -> str:
        seen: List[str] = []
        for item in items:
            value = str(item.get(field) or "").strip()
            if value and value not in seen:
                seen.append(value)
        return "；".join(seen[:4])

    merged_works: List[str] = []
    merged_quotes: List[str] = []
    for item in items:
        for work in item.get("works") or []:
            clean = str(work or "").strip()
            if clean and clean not in merged_works:
                merged_works.append(clean)
        for quote in item.get("quoteLines") or []:
            clean = str(quote or "").strip()
            if clean and clean not in merged_quotes:
                merged_quotes.append(clean)

    base["event"] = merge_text("event") or str(base.get("event") or "")
    base["significance"] = merge_text("significance") or str(base.get("significance") or "")
    base["duration"] = merge_text("duration") or str(base.get("duration") or "")
    base["works"] = merged_works
    base["quoteLines"] = merged_quotes
    return base


def collapse_sparse_single_site_locations(
    loc_items: List[Dict[str, object]],
    *,
    extract_works: Callable[[str], List[str]],
) -> List[Dict[str, object]]:
    if len(loc_items) <= 1:
        return loc_items

    groups: Dict[str, List[Dict[str, object]]] = {}
    for item in loc_items:
        key = coord_group_key(item.get("lat"), item.get("lng"))
        if not key:
            continue
        groups.setdefault(key, []).append(item)
    if not groups:
        return loc_items

    concrete_keys = [
        key for key, items in groups.items()
        if any(not is_speculative_location_item(item) for item in items)
    ]
    if len(concrete_keys) == 1:
        return [merge_location_cluster(groups[concrete_keys[0]], extract_works=extract_works)]

    if len(groups) == 1:
        key = next(iter(groups.keys()))
        return [merge_location_cluster(groups[key], extract_works=extract_works)]

    return loc_items


def extract_location_time_bounds(raw: object) -> Tuple[Optional[int], Optional[int]]:
    text = str(raw or "").strip()
    if not text:
        return None, None
    years: List[int] = []
    year_pattern = re.compile(r"(公元前|前)?\s*(\d{1,4})(?=年(?!代))")
    for match in year_pattern.finditer(text):
        try:
            value = int(match.group(2))
        except Exception:
            continue
        era = str(match.group(1) or "").strip()
        years.append(-value if era else value)
    has_explicit_year = bool(re.search(r"(?:公元前|前)?\s*\d{1,4}\s*年(?!代)", text))
    if not years and ("世纪" in text or "年代" in text) and not has_explicit_year:
        return None, None
    if not years:
        for match in re.finditer(r"(?<!\d)(-?\d{1,4})(?!\d)(?!\s*世纪)", text):
            try:
                years.append(int(match.group(1)))
            except Exception:
                continue
    if not years:
        return None, None
    if len(years) == 1:
        return years[0], years[0]
    return min(years), max(years)


def looks_like_death_location(item: Dict[str, object]) -> bool:
    kind = str(item.get("type") or "").strip().lower()
    if kind == "death":
        return True
    text = " ".join(
        str(item.get(key) or "").strip()
        for key in ("event", "significance")
        if str(item.get(key) or "").strip()
    )
    if not text:
        return False
    negated_death_pattern = re.compile(r"(不代表|并非|不是|并不是|非|不属|不算)(?:[^，。；;、,\s]{0,6})(去世|逝世|病逝|身亡|死亡|殒命|辞世|亡故|谢世|终老)")
    if negated_death_pattern.search(text):
        return False
    death_tokens = ("去世", "逝世", "病逝", "身亡", "死亡", "殒命", "惊悸而死", "溺水", "辞世", "亡故", "谢世", "终老", "安葬", "葬于")
    if any(token in text for token in death_tokens):
        return True
    return bool(re.search(r"(?:^|[，。；;、,\s])卒(?:于|地|处)?(?:$|[，。；;、,\s])", text))


def infer_location_significance(item: Dict[str, object], *, person_name: str = "") -> str:
    existing = str(item.get("significance") or "").strip()
    if existing:
        return existing
    event = str(item.get("event") or "").strip()
    name = str(item.get("name") or item.get("modernName") or item.get("ancientName") or "此地").strip() or "此地"
    kind = str(item.get("type") or "").strip().lower()
    if kind == "birth":
        return f"{name}是{person_name or '该人物'}人生起点的重要地点，也为理解其出身背景与后世纪念提供线索。"
    if kind == "death" or looks_like_death_location(item):
        return f"{name}对应{person_name or '该人物'}人生终章，是观察其命运转折与历史结局的重要节点。"
    if not event:
        return f"{name}是{person_name or '该人物'}人生轨迹中的关键停驻点，可据此串联其生平阶段变化。"
    if any(token in event for token in ("起兵", "结义", "投军", "出仕", "赴京", "登第", "受命", "入朝")):
        return f"{name}标志着{person_name or '该人物'}人生阶段的开启或身份转折，是其后续经历的重要起点。"
    if any(token in event for token in ("镇守", "驻守", "坐镇", "长期", "居于", "讲学", "任职")):
        return f"{name}是{person_name or '该人物'}展开核心活动的重要舞台，体现其在这一阶段的主要职责与影响。"
    if any(token in event for token in ("大败", "击败", "斩", "北伐", "凯旋", "封", "称帝", "建功", "水淹")):
        return f"{name}见证了{person_name or '该人物'}的重要功业节点，也是其历史声望形成的关键场域。"
    if any(token in event for token in ("败走", "失守", "被贬", "流放", "遇害", "擒杀", "失荆州", "兵败")):
        return f"{name}对应{person_name or '该人物'}命运转折甚至失势阶段，对理解其人生起伏具有关键意义。"
    return f"{name}与“{event}”这一事件紧密相关，是理解{person_name or '该人物'}生平轨迹的重要地点。"


def sort_profile_locations(loc_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if len(loc_items) <= 1:
        return loc_items
    bounds: List[Tuple[Optional[int], Optional[int]]] = [
        extract_location_time_bounds(item.get("time")) for item in loc_items
    ]

    def _kind(item: Dict[str, object]) -> str:
        if str(item.get("type") or "").strip().lower() == "birth":
            return "birth"
        if str(item.get("type") or "").strip().lower() == "death" or looks_like_death_location(item):
            return "death"
        return "normal"

    kinds = [_kind(item) for item in loc_items]
    propagated_start: List[Optional[int]] = [b[0] for b in bounds]
    propagated_end: List[Optional[int]] = [b[1] for b in bounds]
    for i, start in enumerate(propagated_start):
        if start is not None:
            continue
        if kinds[i] != "normal":
            continue
        left: Optional[int] = None
        for j in range(i - 1, -1, -1):
            if propagated_start[j] is not None and kinds[j] != "death":
                left = propagated_start[j]
                break
        right: Optional[int] = None
        for j in range(i + 1, len(propagated_start)):
            if propagated_start[j] is not None and kinds[j] != "death":
                right = propagated_start[j]
                break
        if left is None or right is None:
            continue
        propagated_start[i] = (left + right) // 2
        if propagated_end[i] is None:
            propagated_end[i] = propagated_start[i]

    indexed = list(enumerate(loc_items))

    def _key(entry: Tuple[int, Dict[str, object]]) -> Tuple[int, int, int, int]:
        idx, _item = entry
        start_year = propagated_start[idx]
        end_year = propagated_end[idx]
        kind = kinds[idx]
        if kind == "birth":
            rank = 0
        elif kind == "death":
            rank = 2
        else:
            rank = 1
        if rank == 0 and start_year is None:
            year_key = -(10**9)
        else:
            year_key = start_year if start_year is not None else 10**9
        end_key = end_year if end_year is not None else year_key
        return (year_key, rank, end_key, idx)

    indexed.sort(key=_key)
    return [item for _, item in indexed]


def resolve_life_event_coord(
    *,
    raw_text: str,
    raw_loc: str,
    geocode_loc: str,
    modern_loc: str,
    coords_cache: Dict[str, Coord],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    allow_geocode: bool,
) -> Optional[Coord]:
    if not geocode_loc:
        return None
    geo_name = parser_utils._pick_geocode_name(modern_loc or geocode_loc or raw_loc)
    coord = (
        parser_utils._extract_inline_coord_pair(raw_text)
        or fuzzy_coord_lookup(coords_cache, [geo_name, modern_loc, geocode_loc, raw_loc])
    )
    if not coord:
        coord = lookup_coords_from_historical_index(geo_name, modern_loc, geocode_loc, raw_loc)
    if allow_geocode and (not coord) and geo_name:
        coord = resolve_place_coord(geo_name, None, geocode_loc, modern_loc)
    return coord


def build_location_items(
    *,
    locations: List[Dict[str, object]],
    coords_cache: Dict[str, Coord],
    coords_search_map: Dict[str, str],
    person_name: str,
    fallback_person: str,
    allow_geocode: bool,
    event_callback: Optional[callable],
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    extract_works: Callable[[str], List[str]],
    split_quote_lines: Callable[[str], List[str]],
) -> List[Dict[str, object]]:
    loc_items: List[Dict[str, object]] = []
    for loc in locations:
        loc_text = loc.get("location") or loc.get("name") or ""
        ancient, modern = split_ancient_modern(loc_text, event_callback)
        geo_name = parser_utils._pick_geocode_name(modern or loc_text or loc.get("name") or ancient)
        coord_candidates = [geo_name, modern, loc_text, loc.get("name") or "", ancient]
        coord = parser_utils._extract_inline_coord_pair(loc_text) or fuzzy_coord_lookup(coords_cache, coord_candidates)
        if not coord:
            coord = loose_coord_lookup(coords_cache, coord_candidates)
        search_name = ""
        for candidate_key in [
            geo_name,
            parser_utils._pick_geocode_name(modern) if modern else "",
            parser_utils._pick_geocode_name(loc_text) if loc_text else "",
            parser_utils._pick_geocode_name(loc.get("name") or "") if loc.get("name") else "",
        ]:
            if candidate_key and candidate_key in coords_search_map:
                search_name = coords_search_map[candidate_key]
                break
        if (not search_name) and coords_search_map:
            for candidate_key in coord_candidates:
                loose_candidate = loose_place_key(candidate_key)
                if not loose_candidate:
                    continue
                for raw_key, raw_search in coords_search_map.items():
                    if loose_candidate in loose_place_key(raw_key):
                        search_name = raw_search
                        break
                if search_name:
                    break
        if not coord:
            coord = lookup_coords_from_historical_index(
                geo_name,
                search_name,
                ancient,
                modern,
                loc_text,
                loc.get("name") or "",
            )
        geocode_candidates = []
        if search_name:
            geocode_candidates.append(search_name)
        if geo_name and geo_name not in geocode_candidates:
            geocode_candidates.append(geo_name)
        if allow_geocode and (not coord):
            for candidate in geocode_candidates:
                year = None
                try:
                    match = re.search(r"(?<!\d)(-?\d{1,4})(?!\d)", str(loc.get("time") or ""))
                    year = int(match.group(1)) if match else None
                except Exception:
                    year = None
                coord = resolve_place_coord(
                    candidate,
                    year,
                    ancient,
                    modern,
                    loc_text,
                    loc.get("name") or "",
                )
                if coord:
                    break
        if not coord:
            continue
        works = extract_works(" ".join([loc.get("event", ""), loc.get("significance", "")]))
        quote_lines = split_quote_lines(loc.get("quotes", ""))
        inferred_significance = infer_location_significance(
            loc,
            person_name=person_name or fallback_person,
        )
        loc_items.append(
            {
                "name": loc.get("name") or geo_name,
                "ancientName": ancient or loc.get("name") or "",
                "modernName": modern or loc_text,
                "lat": coord[0],
                "lng": coord[1],
                "coordSystem": "WGS84",
                "type": loc.get("type", "normal"),
                "event": loc.get("event", ""),
                "time": loc.get("time", ""),
                "duration": loc.get("duration", ""),
                "significance": inferred_significance,
                "works": works,
                "quoteLines": quote_lines,
            }
        )
    return loc_items


def build_fallback_location_items(
    *,
    coords_cache: Dict[str, Coord],
    birth_coord: Optional[Coord],
    death_coord: Optional[Coord],
    birth_loc: str,
    death_loc: str,
    birth_modern: str,
    death_modern: str,
    birth_date: str,
    death_date: str,
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    event_callback: Optional[callable],
) -> List[Dict[str, object]]:
    if coords_cache and not (birth_coord or death_coord):
        return [
            {
                "name": key,
                "ancientName": "",
                "modernName": key,
                "lat": coord[0],
                "lng": coord[1],
                "coordSystem": "WGS84",
                "type": "move",
                "event": "",
                "time": "",
                "duration": "",
                "significance": "",
                "works": [],
                "quoteLines": [],
            }
            for key, coord in coords_cache.items()
            if str(key or "").strip()
        ]
    if birth_coord or death_coord:
        birth_ancient, birth_modern_2 = split_ancient_modern(birth_loc, event_callback)
        death_ancient, death_modern_2 = split_ancient_modern(death_loc, event_callback)
        fallback_items: List[Dict[str, object]] = []
        if birth_coord:
            fallback_items.append(
                {
                    "name": birth_modern_2 or birth_modern or birth_loc or "出生地",
                    "ancientName": birth_ancient or "",
                    "modernName": birth_modern_2 or birth_modern or birth_loc or "",
                    "lat": birth_coord[0],
                    "lng": birth_coord[1],
                    "coordSystem": "WGS84",
                    "type": "birth",
                    "event": "出生",
                    "time": birth_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                }
            )
        if death_coord:
            fallback_items.append(
                {
                    "name": death_modern_2 or death_modern or death_loc or "去世地",
                    "ancientName": death_ancient or "",
                    "modernName": death_modern_2 or death_modern or death_loc or "",
                    "lat": death_coord[0],
                    "lng": death_coord[1],
                    "coordSystem": "WGS84",
                    "type": "death",
                    "event": "去世",
                    "time": death_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                }
            )
        return fallback_items
    return []
