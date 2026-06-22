from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

from ..core import parsers as parser_utils
from ..core.project_paths import data_corpus_file_path
from . import profile_location_utils
from . import profile_text_utils


Coord = Tuple[float, float]
_SUMMARY_INDEX_PATH = data_corpus_file_path("people_summary_index.json")
_WORK_SUMMARY_INDEX_PATH = data_corpus_file_path("work_summary_index.json")


def extract_works(text: str) -> List[str]:
    return profile_text_utils.extract_works(text)


def _loose_place_key(text: str) -> str:
    return profile_location_utils.loose_place_key(text)


def _loose_coord_lookup(coords_cache: Dict[str, Coord], candidates: List[str]) -> Optional[Coord]:
    return profile_location_utils.loose_coord_lookup(coords_cache, candidates)


def _split_person_alias_values(*values: object) -> List[str]:
    out: List[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        for part in re.split(r"[、，,；;/\s]+", text):
            alias = str(part or "").strip()
            if alias and alias not in out:
                out.append(alias)
    return out


def _merge_unique_strings(*values: object) -> List[str]:
    out: List[str] = []
    for raw in values:
        if isinstance(raw, list):
            items = raw
        else:
            items = [raw]
        for item in items:
            text = str(item or "").strip()
            if text and text not in out:
                out.append(text)
    return out


@lru_cache(maxsize=1)
def _load_people_summary_index() -> Dict[str, Dict[str, object]]:
    try:
        payload = json.loads(_SUMMARY_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for key, value in items.items():
        name = str(key or "").strip()
        if name and isinstance(value, dict):
            out[name] = value
    return out


def _get_person_summary_item(person_name: str) -> Dict[str, object]:
    name = str(person_name or "").strip()
    if not name:
        return {}
    return dict(_load_people_summary_index().get(name) or {})


@lru_cache(maxsize=1)
def _load_work_summary_index() -> Dict[str, Dict[str, object]]:
    try:
        payload = json.loads(_WORK_SUMMARY_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for key, value in items.items():
        title = str(key or "").strip()
        if not title or not isinstance(value, dict):
            continue
        item = dict(value)
        item.setdefault("title", title)
        for alias in _work_title_aliases(title):
            if alias and alias not in out:
                out[alias] = item
        for alias in item.get("aliases") or []:
            for normalized in _work_title_aliases(str(alias or "")):
                if normalized and normalized not in out:
                    out[normalized] = item
    return out


def _get_work_summary_item(title: str) -> Dict[str, object]:
    clean_title = str(title or "").strip()
    if not clean_title:
        return {}
    items = _load_work_summary_index()
    for alias in _work_title_aliases(clean_title):
        item = items.get(alias)
        if isinstance(item, dict):
            return dict(item)
    return {}


def _collect_profile_work_summaries(
    *,
    normalized_md: str,
    highlight_works: List[str],
    locations: List[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    titles = _merge_unique_strings(
        extract_works(normalized_md),
        highlight_works,
        [str(work or "").strip() for loc in locations for work in (loc.get("works") or [])],
    )
    out: Dict[str, Dict[str, object]] = {}
    for raw_title in titles:
        item = _get_work_summary_item(raw_title)
        if not item:
            continue
        key = str(item.get("title") or raw_title or "").strip()
        if key and key not in out:
            out[key] = item
    return out


def _coord_group_key(lat: object, lng: object) -> str:
    return profile_location_utils.coord_group_key(lat, lng)


def _is_speculative_location_item(item: Dict[str, object]) -> bool:
    return profile_location_utils.is_speculative_location_item(item)


def _choose_primary_location(items: List[Dict[str, object]]) -> Dict[str, object]:
    return profile_location_utils.choose_primary_location(items, extract_works=extract_works)


def _merge_location_cluster(items: List[Dict[str, object]]) -> Dict[str, object]:
    return profile_location_utils.merge_location_cluster(items, extract_works=extract_works)


def _collapse_sparse_single_site_locations(loc_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return profile_location_utils.collapse_sparse_single_site_locations(loc_items, extract_works=extract_works)


def _extract_location_time_bounds(raw: object) -> Tuple[Optional[int], Optional[int]]:
    return profile_location_utils.extract_location_time_bounds(raw)


def _looks_like_death_location(item: Dict[str, object]) -> bool:
    return profile_location_utils.looks_like_death_location(item)


def _infer_location_significance(
    item: Dict[str, object],
    *,
    person_name: str = "",
) -> str:
    return profile_location_utils.infer_location_significance(item, person_name=person_name)


def _sort_profile_locations(loc_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return profile_location_utils.sort_profile_locations(loc_items)


def _work_title_aliases(title: str) -> List[str]:
    return profile_text_utils.work_title_aliases(title)


def extract_work_texts(md: str) -> Dict[str, str]:
    return profile_text_utils.extract_work_texts(md)


def split_quote_lines(text: str) -> List[str]:
    return profile_text_utils.split_quote_lines(text)


def extract_title_from_text(text: str) -> str:
    return profile_text_utils.extract_title_from_text(text)


def _clean_short_review_text(text: str, *, max_len: int = 88) -> str:
    return profile_text_utils.clean_short_review_text(text, max_len=max_len)


def choose_short_review(
    *,
    info: Dict[str, str],
    locations: List[Dict[str, str]],
    work_texts: Dict[str, str],
    historical_reviews: List[str],
    fallback: str = "",
) -> str:
    return profile_text_utils.choose_short_review(
        info=info,
        locations=locations,
        work_texts=work_texts,
        historical_reviews=historical_reviews,
        fallback=fallback,
    )


def build_points(
    places: List[Dict[str, str]],
    events: List[Dict[str, str]],
    *,
    allow_geocode: bool = True,
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    geocode_city: Callable[[str], Optional[Coord]],
    event_callback: Optional[callable] = None,
) -> List[Dict[str, object]]:
    del event_callback
    if not isinstance(places, list) or not isinstance(events, list):
        return []
    pts: List[Dict[str, object]] = []
    for p in places:
        name = p.get("modern") or p.get("ancient") or ""
        if not name:
            continue
        coord = lookup_coords_from_historical_index(p.get("ancient") or "", p.get("modern") or "", name)
        if allow_geocode and (not coord):
            coord = geocode_city(name)
        if not coord:
            continue
        lat, lon = coord
        matched = []
        for e in events:
            desc = e.get("desc") or ""
            if name and name in desc:
                matched.append(e)
        lines = [f"**{name}**", ""]
        items = matched[:6] if matched else events[:3]
        for e in items:
            era = e.get("era", "")
            ad = e.get("ad", "")
            desc = e.get("desc", "")
            lines.append(f"- {era} / {ad}：{desc}")
        pts.append({"name": name, "lat": lat, "lon": lon, "md": "\n".join(lines)})
    return pts


def extract_intro_fields(md: str) -> Dict[str, str]:
    if not isinstance(md, str):
        return {"朝代": "", "身份": "", "生卒年": "", "主要事件": "", "主要作品": "", "历史地位": "", "一生行程": ""}
    lines = md.splitlines()
    in_intro = False
    fields = {"朝代": "", "身份": "", "生卒年": "", "主要事件": "", "主要作品": "", "历史地位": "", "一生行程": ""}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            in_intro = title == "简介"
            continue
        if not in_intro:
            continue
        t = stripped
        if "：" in t:
            k, v = t.split("：", 1)
            k = k.strip()
            v = v.strip()
            if k in fields:
                fields[k] = v
    if any(fields.values()):
        return fields
    info = parser_utils._parse_basic_info(md)
    if info:
        if not fields["朝代"]:
            fields["朝代"] = info.get("时代", "") or info.get("朝代", "")
        if not fields["身份"]:
            fields["身份"] = info.get("主要身份", "")
        if not fields["历史地位"]:
            fields["历史地位"] = info.get("历史地位", "")
        if not fields["主要事件"]:
            fields["主要事件"] = info.get("主要成就", "")
        if not fields["生卒年"]:
            birth_text = info.get("出生", "")
            death_text = info.get("去世", "")
            birth_date, _ = parser_utils._parse_date_location(birth_text, ["出生于", "生于"])
            death_date, _ = parser_utils._parse_date_location(death_text, ["卒于", "去世于", "卒"])
            if birth_date or death_date:
                fields["生卒年"] = f"{birth_date}-{death_date}".strip("-")
            else:
                fields["生卒年"] = " / ".join([t for t in [birth_text, death_text] if t])
    in_section = False
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            if "人生足迹地图说明" in title:
                in_section = True
                continue
            if in_section:
                break
        if not in_section or "：" not in line:
            continue
        label = ""
        m = re.search(r"\*\*(.+?)\*\*", line)
        if m:
            label = m.group(1).strip()
        val = line.split("：", 1)[-1].strip()
        if label == "行程概览":
            fields["一生行程"] = val
            break
        if not fields["一生行程"] and label in {"时间跨度", "地理范围"}:
            fields["一生行程"] = val
    return fields


def build_profile_data(
    md: str,
    *,
    fallback_person: str = "",
    allow_geocode: bool = True,
    event_callback: Optional[callable] = None,
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    batch_split_ancient_modern: Callable[[List[str], Optional[callable]], None],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    build_points_fn: Callable[..., List[Dict[str, object]]],
) -> Optional[Dict[str, object]]:
    if not isinstance(md, str) or not md.strip():
        return None
    parsed_doc = parser_utils.parse_story_document(md)
    normalized_md = parsed_doc.normalized_markdown
    info = dict(parsed_doc.basic_info_map)
    locations = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    coords_cache = dict(parsed_doc.coords_table)
    coords_search_map = dict(parsed_doc.coords_search_map)
    if not info:
        fields = extract_intro_fields(normalized_md)
        name_guess = ""
        for line in normalized_md.splitlines():
            t = line.strip()
            if t.startswith("# "):
                name_guess = t[2:].strip()
                break
        if any(fields.values()):
            info = {}
            if name_guess:
                info["姓名"] = name_guess
            dynasty = str(fields.get("朝代") or "").strip()
            if dynasty:
                info["时代"] = dynasty
            identity = str(fields.get("身份") or "").strip()
            if identity:
                info["主要身份"] = identity
            hist = str(fields.get("历史地位") or "").strip()
            if hist:
                info["历史地位"] = hist
            events_text = str(fields.get("主要事件") or "").strip()
            works_text = str(fields.get("主要作品") or "").strip()
            if events_text:
                info["主要成就"] = events_text
            elif works_text:
                info["主要成就"] = works_text
        elif name_guess:
            info = {"姓名": name_guess}
        if not locations and coords_cache:
            locations = [
                {
                    "name": key,
                    "location": key,
                    "type": "move",
                    "time": "",
                    "duration": "",
                    "event": "",
                    "significance": "",
                    "quotes": "",
                }
                for key in coords_cache.keys()
                if str(key or "").strip()
            ]
        if not info and not locations:
            return None
    fallback_person = str(fallback_person or "").strip()
    name_raw = info.get("姓名", "") or fallback_person
    name = name_raw.split("（", 1)[0].strip() or name_raw.strip()
    summary = _get_person_summary_item(name)
    title = (
        str(summary.get("title") or summary.get("honor") or "").strip()
        or extract_title_from_text(info.get("历史地位", ""))
        or extract_title_from_text(name_raw)
        or ""
    )
    description = parsed_doc.overview
    if not description:
        description = "；".join([t for t in [info.get("历史地位", ""), info.get("主要成就", "")] if t])
    description = re.sub(r"-{3,}$", "", description).strip()
    works = extract_works(" ".join([description, info.get("主要成就", ""), info.get("历史地位", "")]))
    work_texts = extract_work_texts(normalized_md)
    short_review = choose_short_review(
        info=info,
        locations=locations,
        work_texts=work_texts,
        historical_reviews=parsed_doc.historical_reviews,
        fallback=title,
    )
    summary_short_review = _clean_short_review_text(
        summary.get("short_review") or summary.get("review") or summary.get("spotlight") or ""
    )
    short_review = summary_short_review or short_review
    birth_text = info.get("出生", "")
    death_text = info.get("去世", "")
    birth_date, birth_loc, birth_geocode_loc = parser_utils._parse_date_location_details(birth_text, ["出生于", "生于"])
    death_date, death_loc, death_geocode_loc = parser_utils._parse_date_location_details(death_text, ["卒于", "去世于", "卒"])

    if not locations:
        try:
            pts = build_points_fn(
                parsed_doc.places,
                parsed_doc.events,
                allow_geocode=allow_geocode,
                event_callback=event_callback,
            )
        except Exception:
            pts = []
        loc_items: List[Dict[str, object]] = []
        for p in pts:
            if not isinstance(p, dict):
                continue
            name0 = str(p.get("name") or "").strip()
            try:
                lat = float(p.get("lat"))  # type: ignore[arg-type]
                lng = float(p.get("lon"))  # type: ignore[arg-type]
            except Exception:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            loc_items.append(
                {
                    "name": name0,
                    "location": name0,
                    "ancient": name0,
                    "modern": "",
                    "lat": lat,
                    "lng": lng,
                    "type": "move",
                    "time": "",
                    "stay": "",
                    "event": "",
                    "meaning": "",
                    "quote": "",
                    "md": str(p.get("md") or ""),
                }
            )
        if loc_items:
            locations = loc_items

    person_key = name or fallback_person
    if person_key in {"徐霞客", "徐弘祖"} or "徐霞客" in name_raw:
        existing_keys = set()
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            raw_loc = str(loc.get("location") or loc.get("name") or "").strip()
            if raw_loc:
                existing_keys.add(profile_location_utils.loose_place_key(raw_loc))
        candidates = [
            ("江苏江阴", "家乡江阴，出发与归终之地"),
            ("浙江天台山", "天台山"),
            ("浙江雁荡山", "雁荡山"),
            ("安徽黄山", "黄山"),
            ("安徽齐云山", "白岳（齐云山）"),
            ("江西庐山", "庐山"),
            ("福建武夷山", "武夷山"),
            ("河南嵩山", "嵩山"),
            ("陕西华山", "华山"),
            ("湖北武当山", "武当山"),
            ("广东罗浮山", "罗浮山"),
            ("广西桂林", "桂林"),
            ("广西阳朔", "阳朔"),
            ("广西漓江", "漓江"),
            ("贵州黄果树瀑布", "黄果树瀑布"),
            ("云南鸡足山", "鸡足山"),
            ("云南大理", "大理"),
            ("云南丽江", "丽江"),
            ("湖南衡山", "衡山"),
            ("山东泰山", "泰山"),
            ("山西五台山", "五台山"),
            ("河北盘山", "盘山"),
        ]
        extra = []
        for loc_text, note in candidates:
            key = profile_location_utils.loose_place_key(loc_text)
            if not key or key in existing_keys:
                continue
            existing_keys.add(key)
            extra.append(
                {
                    "name": loc_text,
                    "location": loc_text,
                    "type": "travel",
                    "time": "",
                    "duration": "",
                    "event": f"行旅至{note}" if note else "",
                    "significance": "",
                    "quotes": "",
                }
            )
        if extra:
            locations = list(locations) + extra

    loc_texts = [birth_loc, death_loc]
    loc_texts.extend([loc.get("location") or loc.get("name") or "" for loc in locations])
    batch_split_ancient_modern(loc_texts, event_callback=event_callback)
    lifespan = info.get("享年", "")
    birth_modern = split_ancient_modern(birth_geocode_loc or birth_loc, event_callback)[1]
    death_modern = split_ancient_modern(death_geocode_loc or death_loc, event_callback)[1]
    birth_coord = profile_location_utils.resolve_life_event_coord(
        raw_text=birth_text,
        raw_loc=birth_loc,
        geocode_loc=birth_geocode_loc,
        modern_loc=birth_modern,
        coords_cache=coords_cache,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        allow_geocode=allow_geocode,
    )
    death_coord = profile_location_utils.resolve_life_event_coord(
        raw_text=death_text,
        raw_loc=death_loc,
        geocode_loc=death_geocode_loc,
        modern_loc=death_modern,
        coords_cache=coords_cache,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        allow_geocode=allow_geocode,
    )

    dynasty = (info.get("时代", "") or info.get("朝代", "")).strip()
    highlight_status = str(summary.get("status") or info.get("历史地位", "") or "").strip()
    highlight_identities = str(summary.get("identities") or info.get("主要身份", "") or "").strip()
    highlight_achievements = str(summary.get("achievements") or info.get("主要成就", "") or "").strip()
    highlight_works = _merge_unique_strings(summary.get("works") or [], works)
    summary_reviews = summary.get("reviews")
    if not isinstance(summary_reviews, list):
        summary_reviews = []
    highlight_reviews = _merge_unique_strings(summary_reviews, parsed_doc.historical_reviews)
    courtesy_name = str(info.get("字", "") or info.get("表字", "")).strip()
    art_name = str(info.get("号", "") or info.get("别号", "")).strip()
    aliases = _split_person_alias_values(
        info.get("别名", ""),
        info.get("别称", ""),
        info.get("曾用名", ""),
        info.get("又名", ""),
        courtesy_name,
        art_name,
    )
    person = {
        "name": name or "人物",
        "title": title,
        "description": description,
        "quote": short_review or title,
        "shortReview": short_review or title,
        "dynasty": dynasty,
        "courtesyName": courtesy_name,
        "artName": art_name,
        "aliases": aliases,
        "birthplace": birth_loc,
        "avatar": "",
        "birth": {
            "date": birth_date,
            "location": birth_loc,
            "lat": birth_coord[0] if birth_coord else None,
            "lng": birth_coord[1] if birth_coord else None,
            "coordSystem": "WGS84" if birth_coord else "",
        },
        "death": {
            "date": death_date,
            "location": death_loc,
            "lat": death_coord[0] if death_coord else None,
            "lng": death_coord[1] if death_coord else None,
            "coordSystem": "WGS84" if death_coord else "",
        },
        "lifespan": lifespan,
        "highlights": {
            "honor": title,
            "status": highlight_status,
            "identities": highlight_identities,
            "achievements": highlight_achievements,
            "works": highlight_works,
            "reviews": highlight_reviews,
        },
    }

    loc_items = profile_location_utils.build_location_items(
        locations=locations,
        coords_cache=coords_cache,
        coords_search_map=coords_search_map,
        person_name=name,
        fallback_person=fallback_person,
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=split_ancient_modern,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        extract_works=extract_works,
        split_quote_lines=split_quote_lines,
    )
    if not loc_items:
        loc_items = profile_location_utils.build_fallback_location_items(
            coords_cache=coords_cache,
            birth_coord=birth_coord,
            death_coord=death_coord,
            birth_loc=birth_loc,
            death_loc=death_loc,
            birth_modern=birth_modern,
            death_modern=death_modern,
            birth_date=birth_date,
            death_date=death_date,
            split_ancient_modern=split_ancient_modern,
            event_callback=event_callback,
        )
    loc_items = _collapse_sparse_single_site_locations(loc_items)
    loc_items = _sort_profile_locations(loc_items)
    work_summaries = _collect_profile_work_summaries(
        normalized_md=normalized_md,
        highlight_works=highlight_works,
        locations=loc_items,
    )
    return {
        "person": person,
        "locations": loc_items,
        "coordinateSystem": "WGS84",
        "mapStyle": {
            "pathColor": "#1e40af",
            "markers": {
                "normal": {"color": "#3498db"},
                "birth": {"color": "#2ecc71"},
                "death": {"color": "#e74c3c"},
            },
        },
        "textbookPoints": parsed_doc.textbook_points,
        "examPoints": parsed_doc.exam_points,
        "workTexts": work_texts,
        "workSummaries": work_summaries,
    }


def load_profile_from_md(
    md: str,
    *,
    fallback_person: str = "",
    allow_geocode: bool = True,
    event_callback: Optional[callable] = None,
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    batch_split_ancient_modern: Callable[[List[str], Optional[callable]], None],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    build_points_fn: Callable[..., List[Dict[str, object]]],
) -> Optional[Dict[str, object]]:
    if not md:
        return None
    return build_profile_data(
        md,
        fallback_person=fallback_person,
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=split_ancient_modern,
        batch_split_ancient_modern=batch_split_ancient_modern,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        build_points_fn=build_points_fn,
    )
