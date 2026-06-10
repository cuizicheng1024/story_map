from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

try:
    from . import parsers as parser_utils
except ImportError:
    import parsers as parser_utils


Coord = Tuple[float, float]
_LITERARY_ROLE_TOKENS = (
    "诗人",
    "词人",
    "文学家",
    "散文家",
    "作家",
    "小说家",
    "剧作家",
    "诗词家",
    "文人",
    "赋家",
)
_HISTORICAL_RECORD_TOKENS = (
    "《史记》",
    "《汉书》",
    "《后汉书》",
    "《三国志》",
    "《晋书》",
    "《宋书》",
    "《南齐书》",
    "《梁书》",
    "《陈书》",
    "《魏书》",
    "《北齐书》",
    "《周书》",
    "《隋书》",
    "《旧唐书》",
    "《新唐书》",
    "《旧五代史》",
    "《新五代史》",
    "《宋史》",
    "《辽史》",
    "《金史》",
    "《元史》",
    "《明史》",
    "《清史稿》",
    "《资治通鉴》",
    "史载",
    "记载",
    "载曰",
    "评曰",
    "本纪",
    "列传",
)


def extract_works(text: str) -> List[str]:
    if not text:
        return []
    items = re.findall(r"《([^》]+)》", text)
    seen = set()
    works: List[str] = []
    for item in items:
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            works.append(name)
    return works


def _loose_place_key(text: str) -> str:
    cleaned = parser_utils._pick_geocode_name(str(text or ""))
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（(].*?[）)]", "", cleaned)
    cleaned = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", cleaned)
    for token in ("风景区", "景区", "古战场", "旧址", "遗址", "故居", "博物馆"):
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"[省市区县州郡府镇乡村旗盟]", "", cleaned)
    return cleaned.strip()


def _loose_coord_lookup(coords_cache: Dict[str, Coord], candidates: List[str]) -> Optional[Coord]:
    if not coords_cache:
        return None
    loose_candidates = [_loose_place_key(candidate) for candidate in candidates if str(candidate or "").strip()]
    loose_candidates = [candidate for candidate in loose_candidates if candidate]
    if not loose_candidates:
        return None
    scored: List[Tuple[int, str]] = []
    for raw_key in coords_cache.keys():
        key = str(raw_key or "").strip()
        if not key:
            continue
        loose_key = _loose_place_key(key)
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


def _register_work_text(store: Dict[str, str], title: str, text: str) -> None:
    clean_title = str(title or "").strip()
    clean_text = str(text or "").strip()
    if not clean_title or not clean_text:
        return
    clean_text = re.sub(r"\s*\n\s*", "\n", clean_text).strip()
    aliases = [clean_title]
    short_title = clean_title.split("·", 1)[0].strip()
    if short_title and short_title not in aliases:
        aliases.append(short_title)
    for alias in aliases:
        if not alias:
            continue
        existing = str(store.get(alias) or "").strip()
        if not existing or len(clean_text) > len(existing):
            store[alias] = clean_text


def _register_work_context(store: Dict[str, str], title: str, text: str) -> None:
    clean_title = str(title or "").strip()
    clean_text = str(text or "").strip()
    if not clean_title or not clean_text:
        return
    aliases = [clean_title]
    short_title = clean_title.split("·", 1)[0].strip()
    if short_title and short_title not in aliases:
        aliases.append(short_title)
    if any(str(store.get(alias) or "").strip() for alias in aliases):
        return
    _register_work_text(store, clean_title, clean_text)


def extract_work_texts(md: str) -> Dict[str, str]:
    if not isinstance(md, str) or not md.strip():
        return {}
    work_texts: Dict[str, str] = {}
    for raw_line in md.splitlines():
        line = str(raw_line or "").strip().lstrip("-").strip()
        if "《" not in line:
            continue
        for title, quote in re.findall(r"《([^》]{1,80})》\s*[：:]\s*[“\"「](.+?)[”\"」]", line):
            _register_work_text(work_texts, title, quote)
    for raw_line in md.splitlines():
        line = str(raw_line or "").strip()
        if "《" not in line:
            continue
        context = re.sub(r"^\s*[-*•]\s*", "", line)
        context = re.sub(r"\*\*", "", context).strip()
        context = re.sub(r"\s+", " ", context)
        if len(context) > 140:
            context = context[:137].rstrip() + "..."
        for title in re.findall(r"《([^》]{1,80})》", line):
            _register_work_context(work_texts, title, context)
    return work_texts


def split_quote_lines(text: str) -> List[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"[；;]\s*", text) if p.strip()]


def extract_title_from_text(text: str) -> str:
    m = re.search(r"“([^”]+)”", text)
    if m:
        return m.group(1).strip()
    return ""


def _clean_short_review_text(text: str, *, max_len: int = 88) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"^\s*[-*•]\s*", "", raw)
    raw = re.sub(r"^\d+\.\s*", "", raw)
    raw = raw.replace("**", "").strip()
    quoted = re.search(r"[“\"「『](.+?)[”\"」』]", raw)
    if quoted and str(quoted.group(1) or "").strip():
        return str(quoted.group(1) or "").strip()
    trimmed = raw
    if "：" in trimmed:
        trimmed = trimmed.split("：", 1)[1].strip()
    elif ":" in trimmed:
        trimmed = trimmed.split(":", 1)[1].strip()
    trimmed = re.split(r"\s*(?:——|--|—)\s*", trimmed, maxsplit=1)[0].strip()
    trimmed = re.sub(r"[（(][^）)]{0,40}[）)]\s*$", "", trimmed).strip()
    trimmed = trimmed.strip("“”\"「」『』")
    trimmed = re.sub(r"\s+", " ", trimmed)
    if not trimmed:
        return ""
    if len(trimmed) > max_len:
        trimmed = trimmed[: max_len - 1].rstrip() + "…"
    return trimmed


def _is_literary_person(info: Dict[str, str]) -> bool:
    haystack = " ".join(
        [
            str(info.get("主要身份") or ""),
            str(info.get("历史地位") or ""),
            str(info.get("主要成就") or ""),
        ]
    )
    return any(token in haystack for token in _LITERARY_ROLE_TOKENS)


def _is_historical_record_review(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(token in raw for token in _HISTORICAL_RECORD_TOKENS)


def _is_literary_review(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw or _is_historical_record_review(raw):
        return False
    return "《" in raw and "》" in raw


def _dedupe_review_candidates(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        cleaned = _clean_short_review_text(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _collect_self_review_candidates(locations: List[Dict[str, str]], work_texts: Dict[str, str]) -> Tuple[List[str], List[str]]:
    raw_candidates: List[str] = []
    for loc in locations:
        raw_candidates.extend(split_quote_lines(str(loc.get("quotes") or "")))
    direct_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" not in str(item or "")])
    work_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" in str(item or "")])
    work_candidates.extend(_dedupe_review_candidates([str(text or "") for text in work_texts.values()]))
    return direct_candidates, _dedupe_review_candidates(work_candidates)


def choose_short_review(
    *,
    info: Dict[str, str],
    locations: List[Dict[str, str]],
    work_texts: Dict[str, str],
    historical_reviews: List[str],
    fallback: str = "",
) -> str:
    self_direct_candidates, self_work_candidates = _collect_self_review_candidates(locations, work_texts)
    literary_review_raw = [item for item in historical_reviews if _is_literary_review(item)]
    record_review_raw = [item for item in historical_reviews if _is_historical_record_review(item)]
    literary_review_candidates = _dedupe_review_candidates(literary_review_raw)
    record_review_candidates = _dedupe_review_candidates(record_review_raw)
    categorized_raw = set(literary_review_raw + record_review_raw)
    generic_review_candidates = _dedupe_review_candidates([item for item in historical_reviews if item not in categorized_raw])
    candidate_groups = (
        [self_work_candidates, self_direct_candidates, literary_review_candidates, record_review_candidates, generic_review_candidates]
        if _is_literary_person(info)
        else [literary_review_candidates, record_review_candidates, self_direct_candidates, self_work_candidates, generic_review_candidates]
    )
    for group in candidate_groups:
        for item in group:
            if str(item or "").strip():
                return str(item).strip()
    return _clean_short_review_text(fallback)


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
    name_raw = info.get("姓名", "")
    name = name_raw.split("（", 1)[0].strip() or name_raw.strip()
    title = extract_title_from_text(info.get("历史地位", "")) or extract_title_from_text(name_raw) or ""
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
    birth_text = info.get("出生", "")
    death_text = info.get("去世", "")
    birth_date, birth_loc = parser_utils._parse_date_location(birth_text, ["出生于", "生于"])
    death_date, death_loc = parser_utils._parse_date_location(death_text, ["卒于", "去世于", "卒"])

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

    loc_texts = [birth_loc, death_loc]
    loc_texts.extend([loc.get("location") or loc.get("name") or "" for loc in locations])
    batch_split_ancient_modern(loc_texts, event_callback=event_callback)
    lifespan = info.get("享年", "")
    birth_modern = split_ancient_modern(birth_loc, event_callback)[1]
    death_modern = split_ancient_modern(death_loc, event_callback)[1]
    birth_geo = parser_utils._pick_geocode_name(birth_modern or birth_loc)
    death_geo = parser_utils._pick_geocode_name(death_modern or death_loc)
    birth_coord = fuzzy_coord_lookup(coords_cache, [birth_geo, birth_modern, birth_loc])
    death_coord = fuzzy_coord_lookup(coords_cache, [death_geo, death_modern, death_loc])
    if not birth_coord:
        birth_coord = lookup_coords_from_historical_index(birth_geo, birth_modern, birth_loc)
    if not death_coord:
        death_coord = lookup_coords_from_historical_index(death_geo, death_modern, death_loc)
    if allow_geocode and (not birth_coord) and birth_geo:
        birth_coord = resolve_place_coord(birth_geo, None, birth_loc, birth_modern)
    if allow_geocode and (not death_coord) and death_geo:
        death_coord = resolve_place_coord(death_geo, None, death_loc, death_modern)

    dynasty = (info.get("时代", "") or info.get("朝代", "")).strip()
    person = {
        "name": name or "人物",
        "title": title,
        "description": description,
        "quote": short_review or title,
        "shortReview": short_review or title,
        "dynasty": dynasty,
        "birthplace": birth_loc,
        "avatar": "",
        "birth": {
            "date": birth_date,
            "location": birth_loc,
            "lat": birth_coord[0] if birth_coord else None,
            "lng": birth_coord[1] if birth_coord else None,
        },
        "death": {
            "date": death_date,
            "location": death_loc,
            "lat": death_coord[0] if death_coord else None,
            "lng": death_coord[1] if death_coord else None,
        },
        "lifespan": lifespan,
        "highlights": {
            "honor": title,
            "status": (info.get("历史地位", "") or "").strip(),
            "identities": (info.get("主要身份", "") or "").strip(),
            "achievements": (info.get("主要成就", "") or "").strip(),
            "works": works,
            "reviews": parsed_doc.historical_reviews,
        },
    }

    loc_items: List[Dict[str, object]] = []
    for loc in locations:
        loc_text = loc.get("location") or loc.get("name") or ""
        ancient, modern = split_ancient_modern(loc_text, event_callback)
        geo_name = parser_utils._pick_geocode_name(modern or loc_text or loc.get("name") or ancient)
        coord_candidates = [geo_name, modern, loc_text, loc.get("name") or "", ancient]
        coord = fuzzy_coord_lookup(coords_cache, coord_candidates)
        if not coord:
            coord = _loose_coord_lookup(coords_cache, coord_candidates)
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
                loose_candidate = _loose_place_key(candidate_key)
                if not loose_candidate:
                    continue
                for raw_key, raw_search in coords_search_map.items():
                    if loose_candidate in _loose_place_key(raw_key):
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
                    m = re.search(r"(?<!\d)(-?\d{1,4})(?!\d)", str(loc.get("time") or ""))
                    year = int(m.group(1)) if m else None
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
        loc_items.append(
            {
                "name": loc.get("name") or geo_name,
                "ancientName": ancient or loc.get("name") or "",
                "modernName": modern or loc_text,
                "lat": coord[0],
                "lng": coord[1],
                "type": loc.get("type", "normal"),
                "event": loc.get("event", ""),
                "time": loc.get("time", ""),
                "duration": loc.get("duration", ""),
                "significance": loc.get("significance", ""),
                "works": works,
                "quoteLines": quote_lines,
            }
        )
    if not loc_items:
        if birth_coord and death_coord:
            birth_ancient, birth_modern_2 = split_ancient_modern(birth_loc, event_callback)
            death_ancient, death_modern_2 = split_ancient_modern(death_loc, event_callback)
            loc_items = [
                {
                    "name": birth_modern_2 or birth_modern or birth_loc or "出生地",
                    "ancientName": birth_ancient or "",
                    "modernName": birth_modern_2 or birth_modern or birth_loc or "",
                    "lat": birth_coord[0],
                    "lng": birth_coord[1],
                    "type": "birth",
                    "event": "出生",
                    "time": birth_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                },
                {
                    "name": death_modern_2 or death_modern or death_loc or "去世地",
                    "ancientName": death_ancient or "",
                    "modernName": death_modern_2 or death_modern or death_loc or "",
                    "lat": death_coord[0],
                    "lng": death_coord[1],
                    "type": "death",
                    "event": "去世",
                    "time": death_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                },
            ]
        else:
            loc_items = []
    return {
        "person": person,
        "locations": loc_items,
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
    }


def load_profile_from_md(
    md: str,
    *,
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
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=split_ancient_modern,
        batch_split_ancient_modern=batch_split_ancient_modern,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        build_points_fn=build_points_fn,
    )
