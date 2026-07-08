from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..core import parsers as parser_utils
from ..core.project_paths import data_corpus_file_path
from ..core.types import (
    Coord,
    CoordCache,
    CoordSearchMap,
    LocationItem,
    PersonRecord,
    ProfileData,
)
from . import profile_location_utils
from . import profile_text_utils

_extract_location_time_bounds = profile_location_utils.extract_location_time_bounds
_work_title_aliases = profile_text_utils.work_title_aliases


_SUMMARY_INDEX_PATH = data_corpus_file_path("people_summary_index.json")
_WORK_SUMMARY_INDEX_PATH = data_corpus_file_path("work_summary_index.json")


def extract_works(text: str) -> List[str]:
    return profile_text_utils.extract_works(text)


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


_FOREIGN_ALIAS_PATH = data_corpus_file_path("foreign_name_aliases.json")


@lru_cache(maxsize=1)
def _load_foreign_aliases() -> Dict[str, Dict[str, str]]:
    try:
        payload = json.loads(_FOREIGN_ALIAS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for key, value in entries.items():
        if isinstance(value, dict):
            out[str(key).strip()] = {
                str(k).strip(): str(v).strip()
                for k, v in value.items()
                if isinstance(v, (str, int, float))
            }
    return out


_HIGHLIGHTS_PATH = data_corpus_file_path("description_highlights.json")


@lru_cache(maxsize=1)
def _load_highlights() -> Dict[str, List[Dict[str, str]]]:
    try:
        return json.loads(_HIGHLIGHTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_highlights(name: str) -> List[Dict[str, str]]:
    return _load_highlights().get(str(name or "").strip(), [])


def _lookup_foreign_alias(name: str) -> Tuple[str, str, str]:
    """返回 (foreign_name, country_en, country_zh)。无匹配则返回空串。"""
    aliases = _load_foreign_aliases()
    info = aliases.get(str(name or "").strip()) or {}
    return (
        str(info.get("foreign_name") or "").strip(),
        str(info.get("country") or "").strip(),
        str(info.get("country_zh") or "").strip(),
    )


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


@lru_cache(maxsize=1)
def _load_portraits_map() -> Dict[str, object]:
    """Load person → portrait metadata mapping.

    Supports two formats:
      - Legacy: ``{"孔子": "孔子-abc.jpg"}``
      - Modern: ``{"孔子": {"file": "孔子-abc.jpg", "source": "real", "source_label": "故宫藏画"}}``
    """
    try:
        path = data_corpus_file_path("portraits_map.json")
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_portrait_filename(*candidates: str) -> str:
    """Return the on-disk portrait filename for a person, trying each candidate name.

    Looks up the curated ``portraits_map.json`` first (so we can pin explicit
    filenames), and falls back to the runtime ``portrait_service`` so alias
    overrides like ``孔丘 -> 孔子`` and `<safe>-<sha1>` filenames still work
    even when the registry key is slightly different from the markdown name.
    """
    for raw in candidates:
        clean = str(raw or "").strip()
        if not clean:
            continue
        mapped = _load_portraits_map().get(clean)
        if isinstance(mapped, str):
            return mapped
        if isinstance(mapped, dict):
            return str(mapped.get("file") or "")
    # 模糊匹配：全名 ↔ 肖像注册表中的简名（如"阿尔伯特·爱因斯坦"↔"爱因斯坦"）
    portraits_map = _load_portraits_map()
    for raw in candidates:
        clean = str(raw or "").strip()
        if not clean:
            continue
        for pm_key, pm_entry in portraits_map.items():
            if not isinstance(pm_entry, dict):
                continue
            if pm_key in clean or clean in pm_key:
                fn = str(pm_entry.get("file") or "")
                if fn:
                    return fn
    try:
        from ..map import portrait_service as _portrait_service
        for raw in candidates:
            clean = str(raw or "").strip()
            if not clean:
                continue
            cached = _portrait_service.portrait_cache_path(clean)
            if cached.exists() and cached.stat().st_size > 0:
                return cached.name
    except Exception:
        pass
    # Last resort: scan the portrait dir for a filename that contains the
    # first candidate's SHA1. This handles the case where the canonical name
    # in the markdown (e.g. ``陶潜``) is not in the curated map but a portrait
    # has been downloaded under the historical alias (``陶渊明``).
    try:
        from ..map import portrait_service as _portrait_service
        for raw in candidates:
            clean = str(raw or "").strip()
            if not clean:
                continue
            portrait_dir = _portrait_service.portrait_dir()
            for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                p = portrait_dir / f"{_portrait_service._safe_filename(clean)}.{ext.lstrip('.')}"
                if p.exists() and p.stat().st_size > 0:
                    return p.name
    except Exception:
        pass
    return ""


def _resolve_portrait_source(*candidates: str) -> dict:
    """Return portrait source metadata for a person.

    Returns ``{"source": "unknown", "source_label": ""}`` by default.
    Source values: "real", "ai", "wiki", "unknown".
    """
    portraits_map = _load_portraits_map()
    for raw in candidates:
        clean = str(raw or "").strip()
        if not clean:
            continue
        mapped = portraits_map.get(clean)
        if isinstance(mapped, dict):
            source = str(mapped.get("source") or "unknown").strip()
            label = str(mapped.get("source_label") or "").strip()
            if source:
                return {"source": source, "source_label": label}
    # 模糊匹配：全名 ↔ 简名
    for raw in candidates:
        clean = str(raw or "").strip()
        if not clean:
            continue
        for pm_key, pm_entry in portraits_map.items():
            if isinstance(pm_entry, dict) and (pm_key in clean or clean in pm_key):
                source = str(pm_entry.get("source") or "unknown").strip()
                label = str(pm_entry.get("source_label") or "").strip()
                if source:
                    return {"source": source, "source_label": label}
    # 通过已解析的文件名回查 source（处理"孔丘"→"孔子"这类单字差异）
    portrait_file = _resolve_portrait_filename(*candidates)
    if portrait_file:
        for pm_entry in portraits_map.values():
            if isinstance(pm_entry, dict) and pm_entry.get("file") == portrait_file:
                src = str(pm_entry.get("source") or "unknown").strip()
                lbl = str(pm_entry.get("source_label") or "").strip()
                if src:
                    return {"source": src, "source_label": lbl}
        if portrait_file.lower().endswith(".svg"):
            return {"source": "ai", "source_label": "SVG 占位肖像"}
    return {"source": "unknown", "source_label": ""}


def _portrait_source_for_person(*candidates: str) -> dict:
    """Return ``{"avatarSource": ..., "avatarSourceLabel": ...}`` for a person.

    Calls ``_resolve_portrait_source`` once and maps the result into keys
    matching the PersonRecord dict, so callers don't double-dip the disk scan.
    """
    info = _resolve_portrait_source(*candidates)
    return {
        "avatarSource": info.get("source", "unknown"),
        "avatarSourceLabel": info.get("source_label", ""),
    }


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
        for alias in profile_text_utils.work_title_aliases(title):
            if alias and alias not in out:
                out[alias] = item
        for alias in item.get("aliases") or []:
            for normalized in profile_text_utils.work_title_aliases(str(alias or "")):
                if normalized and normalized not in out:
                    out[normalized] = item
    return out


def _get_work_summary_item(title: str) -> Dict[str, object]:
    clean_title = str(title or "").strip()
    if not clean_title:
        return {}
    items = _load_work_summary_index()
    for alias in profile_text_utils.work_title_aliases(clean_title):
        item = items.get(alias)
        if isinstance(item, dict):
            return dict(item)
    return {}


def _collect_profile_work_summaries(
    *,
    normalized_md: str,
    person_name: str,
    highlight_works: List[str],
    locations: List[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    titles = _merge_unique_strings(
        extract_works(normalized_md),
        highlight_works,
        [str(work or "").strip() for loc in locations for work in (loc.get("works") or [])],
    )
    titles = _sanitize_person_works(person_name, titles)
    out: Dict[str, Dict[str, object]] = {}
    for raw_title in titles:
        item = _get_work_summary_item(raw_title)
        key = str((item or {}).get("title") or raw_title or "").strip()
        item = _apply_person_work_summary_override(person_name, key or raw_title, item)
        if not item:
            continue
        key = str(item.get("title") or raw_title or "").strip()
        if key and key not in out:
            out[key] = item
    return out


_LOCATION_POSTER_OVERRIDES_PATH = data_corpus_file_path("location_poster_overrides.json")


@lru_cache(maxsize=1)
def _load_location_poster_overrides() -> Dict[str, Dict[str, Dict[str, str]]]:
    try:
        return json.loads(_LOCATION_POSTER_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _attach_location_posters(person_name: str, locations: List[Dict[str, object]]) -> List[Dict[str, object]]:
    overrides = _load_location_poster_overrides().get(str(person_name or "").strip()) or {}
    if not overrides:
        return locations
    updated: List[Dict[str, object]] = []
    for item in locations:
        loc = dict(item or {})
        name_candidates = [
            str(loc.get("name") or "").strip(),
            str(loc.get("ancientName") or "").strip(),
            str(loc.get("modernName") or "").strip(),
        ]
        for key, value in overrides.items():
            needle = str(key or "").strip()
            if needle and any(needle in candidate for candidate in name_candidates if candidate):
                loc["poster"] = dict(value)
                break
        updated.append(loc)
    return updated


# ── Person / work override data ──────────────────────────────────────────
# All override data is stored in JSON files under data/corpus/ so that
# corrections can be reviewed and edited independently of code.

_PERSON_WORK_EXCLUSIONS_PATH = data_corpus_file_path("person_work_exclusions.json")
_PERSON_PREFERRED_WORKS_PATH = data_corpus_file_path("person_preferred_works.json")
_PERSON_ACHIEVEMENT_REPLACEMENTS_PATH = data_corpus_file_path("person_achievement_replacements.json")
_PERSON_SUMMARY_OVERRIDES_PATH = data_corpus_file_path("person_summary_overrides.json")
_PERSON_WORK_SUMMARY_OVERRIDES_PATH = data_corpus_file_path("person_work_summary_overrides.json")


@lru_cache(maxsize=1)
def _load_person_work_exclusions() -> Dict[str, Set[str]]:
    try:
        raw = json.loads(_PERSON_WORK_EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Set[str]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            out[str(key).strip()] = {str(v).strip() for v in value if str(v).strip()}
    return out


@lru_cache(maxsize=1)
def _load_person_preferred_works() -> Dict[str, List[str]]:
    try:
        return json.loads(_PERSON_PREFERRED_WORKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_person_achievement_replacements() -> Dict[str, Dict[str, str]]:
    try:
        return json.loads(_PERSON_ACHIEVEMENT_REPLACEMENTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_person_summary_overrides() -> Dict[str, Dict[str, object]]:
    try:
        return json.loads(_PERSON_SUMMARY_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_person_work_summary_overrides() -> Dict[Tuple[str, str], Dict[str, object]]:
    try:
        raw = json.loads(_PERSON_WORK_SUMMARY_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, list):
        return {}
    out: Dict[Tuple[str, str], Dict[str, object]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        person = str(entry.get("person") or "").strip()
        title = str(entry.get("title") or "").strip()
        data = entry.get("data")
        if person and title and isinstance(data, dict):
            out[(person, title)] = data
    return out


def _filter_person_works(person_name: str, works: List[str]) -> List[str]:
    exclusions = _load_person_work_exclusions().get(str(person_name or "").strip(), set())
    if not exclusions:
        return works
    return [title for title in works if str(title or "").strip() not in exclusions]


def _sanitize_person_works(person_name: str, works: List[str]) -> List[str]:
    name = str(person_name or "").strip()
    filtered = _filter_person_works(name, list(works or []))
    preferred = _load_person_preferred_works().get(name) or []
    return _merge_unique_strings(filtered, preferred)


def _normalize_person_achievements(person_name: str, achievements: str) -> str:
    text = str(achievements or "").strip()
    replacements = _load_person_achievement_replacements().get(str(person_name or "").strip()) or {}
    for source, target in replacements.items():
        if source:
            text = text.replace(source, target)
    return text


def _merge_person_summary_overrides(person_name: str, summary: Dict[str, object]) -> Dict[str, object]:
    merged = dict(summary or {})
    overrides = _load_person_summary_overrides().get(str(person_name or "").strip()) or {}
    if overrides:
        merged.update(overrides)
    return merged


def _apply_person_work_summary_override(
    person_name: str,
    title: str,
    item: Dict[str, object],
) -> Dict[str, object]:
    merged = dict(item or {})
    overrides = _load_person_work_summary_overrides().get((str(person_name or "").strip(), str(title or "").strip())) or {}
    if overrides:
        merged.update(overrides)
    return merged


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
    info = parser_utils.parse_basic_info(md)
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
            birth_date, _ = parser_utils.parse_date_location(birth_text, ["出生于", "生于"])
            death_date, _ = parser_utils.parse_date_location(death_text, ["卒于", "去世于", "卒"])
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


def _parse_md_and_fallback_info(
    md: str,
) -> Tuple[Any, Dict[str, str], List[Dict[str, object]], Dict[str, Coord], Dict[str, str], str]:
    """Parse markdown document and ensure info / locations are populated.

    Returns (parsed_doc, info, locations, coords_cache, coords_search_map, normalized_md).
    """
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
    return parsed_doc, info, locations, coords_cache, coords_search_map, normalized_md


def _resolve_person_name_and_summary(
    name_raw: str,
    fallback_person: str,
    info: Dict[str, str],
    description: str,
    locations: List[Dict[str, object]],
    normalized_md: str,
    work_texts: Dict[str, str],
    parsed_doc: Any,
) -> Tuple[str, str, str, str, str, List[str]]:
    """Resolve canonical person name, title, description, works, and short review.

    Returns (canonical_name, name, title, description, works, short_review).
    """
    # Strip trailing aliases / descriptions concatenated into 姓名
    canonical_name = re.split(r"[，,、；;：（(]", name_raw, maxsplit=1)[0].strip() or name_raw
    name = canonical_name or name_raw
    summary = _merge_person_summary_overrides(canonical_name, _get_person_summary_item(canonical_name))
    title = (
        str(summary.get("title") or summary.get("honor") or "").strip()
        or extract_title_from_text(info.get("历史地位", ""))
        or extract_title_from_text(name_raw)
        or ""
    )
    if not description:
        description = "；".join([t for t in [info.get("历史地位", ""), info.get("主要成就", "")] if t])
    description = re.sub(r"-{3,}$", "", description).strip()
    works = extract_works(" ".join([description, info.get("主要成就", ""), info.get("历史地位", "")]))
    works = _sanitize_person_works(canonical_name, works)
    short_review = choose_short_review(
        info=info,
        locations=locations,
        work_texts=work_texts,
        historical_reviews=parsed_doc.historical_reviews,
        fallback=title,
    )
    summary_short_review = ""
    for candidate in (
        summary.get("short_review"),
        summary.get("review"),
        summary.get("spotlight"),
    ):
        summary_short_review = _clean_short_review_text(str(candidate or ""))
        if summary_short_review:
            break
    short_review = summary_short_review or short_review
    return canonical_name, name, title, description, works, short_review


def _inject_xu_xiake_candidates(
    person_key: str,
    name_raw: str,
    locations: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Add candidate travel locations for 徐霞客 if missing from source data."""
    if person_key not in {"徐霞客", "徐弘祖"} and "徐霞客" not in name_raw:
        return locations
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
        return list(locations) + extra
    return locations


def _resolve_fallback_locations(
    locations: List[LocationItem],
    parsed_doc: object,
    build_points_fn: Callable[..., List[dict]],
    *,
    allow_geocode: bool,
    event_callback: Optional[callable],
) -> List[LocationItem]:
    """Phase 3b: build location items from parsed places/events when no locations exist."""
    if locations:
        return locations
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
        loc_items.append({
            "name": name0, "location": name0, "ancient": name0, "modern": "",
            "lat": lat, "lng": lng, "type": "move", "time": "",
            "stay": "", "event": "", "meaning": "", "quote": "",
            "md": str(p.get("md") or ""),
        })
    return loc_items


def _assemble_person_record(
    *,
    canonical_name: str,
    name: str,
    name_raw: str,
    fallback_person: str,
    title: str,
    description: str,
    short_review: str,
    info: Dict[str, str],
    birth_loc: str,
    birth_date: str,
    birth_coord: Optional[Coord],
    death_loc: str,
    death_date: str,
    death_coord: Optional[Coord],
    works: List[str],
    normalized_md: str,
    parsed_doc: object,
) -> PersonRecord:
    """Phase 5: assemble the person metadata record from parsed identity info."""
    dynasty = (info.get("时代", "") or info.get("朝代", "")).strip()
    native_place = parser_utils.extract_native_place_from_story_text(
        normalized_md, basic_info_map=info, overview=description,
    )
    highlight = _merge_person_summary_overrides(canonical_name, _get_person_summary_item(canonical_name))
    highlight_status = str(highlight.get("status") or info.get("历史地位", "") or "").strip()
    highlight_identities = str(highlight.get("identities") or info.get("主要身份", "") or "").strip()
    highlight_achievements = _normalize_person_achievements(
        canonical_name,
        str(highlight.get("achievements") or info.get("主要成就", "") or "").strip(),
    )
    highlight_works = _sanitize_person_works(
        canonical_name,
        _merge_unique_strings(highlight.get("works") or [], works),
    )
    summary_reviews = highlight.get("reviews")
    if not isinstance(summary_reviews, list):
        summary_reviews = []
    highlight_reviews = _merge_unique_strings(summary_reviews, parsed_doc.historical_reviews)

    courtesy_name = str(info.get("字", "") or info.get("表字", "")).strip()
    art_name = str(info.get("号", "") or info.get("别号", "")).strip()
    if not courtesy_name or not art_name:
        paren_match = re.search(r"（([^（）]+)）", name_raw or "")
        if paren_match:
            paren_value = str(paren_match.group(1) or "").strip()
            if not courtesy_name and paren_value.startswith("字"):
                courtesy_name = paren_value[1:].strip() or courtesy_name
            elif not courtesy_name:
                courtesy_name = paren_value
            if not art_name and paren_value.startswith("号"):
                art_name = paren_value[1:].strip() or art_name

    aliases = _split_person_alias_values(
        info.get("别名", ""), info.get("别称", ""), info.get("曾用名", ""),
        info.get("又名", ""), courtesy_name, art_name,
    )
    foreign_name = str(info.get("外文名", "") or info.get("外文", "")).strip()
    if not foreign_name:
        foreign_name = ""
        foreign_country = ""
        foreign_country_zh = ""
        for candidate in (fallback_person, canonical_name, name, name_raw):
            key = str(candidate or "").strip()
            if not key or key == foreign_name:
                continue
            guess_name, guess_country, guess_country_zh = _lookup_foreign_alias(key)
            if guess_name:
                foreign_name = guess_name
                foreign_country = guess_country
                foreign_country_zh = guess_country_zh
                break
        if not foreign_name:
            foreign_country = ""
            foreign_country_zh = ""
    else:
        foreign_country = str(info.get("外文国家", "")).strip()
        foreign_country_zh = str(info.get("国家", "")).strip()

    canonical_name, name = _normalize_foreign_identity(
        canonical_name, name, fallback_person, name_raw, info, foreign_name,
    )

    return {
        "name": canonical_name or "人物",
        "nameRaw": name,
        "foreignName": foreign_name,
        "foreignCountry": foreign_country,
        "foreignCountryZh": foreign_country_zh,
        "title": title,
        "description": description,
        "descriptionHighlights": _get_highlights(canonical_name),
        "quote": short_review or title,
        "shortReview": short_review or title,
        "dynasty": dynasty,
        "courtesyName": courtesy_name,
        "artName": art_name,
        "aliases": aliases,
        "birthplace": birth_loc,
        "nativePlace": native_place,
        "avatar": _resolve_portrait_filename(canonical_name, fallback_person, name_raw, name),
        **_portrait_source_for_person(canonical_name, fallback_person, name_raw, name),
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
        "lifespan": info.get("享年", ""),
        "highlights": {
            "honor": title,
            "status": highlight_status,
            "identities": highlight_identities,
            "achievements": highlight_achievements,
            "works": highlight_works,
            "reviews": highlight_reviews,
        },
    }


def _normalize_foreign_identity(
    canonical_name: str,
    name: str,
    fallback_person: str,
    name_raw: str,
    info: Dict[str, str],
    foreign_name: str,
) -> Tuple[str, str]:
    """Adjust canonical_name for foreign/Latin-name persons."""
    name_field_has_latin = bool(re.search(r"[A-Za-z·]", str(info.get("姓名", "") or "")))
    alias_entry = _load_foreign_aliases().get(str(canonical_name or "").strip()) or {}
    alias_entry_fb = _load_foreign_aliases().get(str(fallback_person or "").strip()) or {}
    is_chinese_native = bool(alias_entry.get("is_chinese_native")) or bool(alias_entry_fb.get("is_chinese_native"))
    country_zh_hint = str(alias_entry.get("country_zh") or alias_entry_fb.get("country_zh") or "").strip()
    if is_chinese_native or country_zh_hint == "中国":
        return canonical_name, name
    if name_field_has_latin and foreign_name and str(fallback_person or "").strip():
        return str(fallback_person).strip(), str(fallback_person).strip()
    return canonical_name, name


def _finalize_profile(
    person: Dict[str, object],
    locations: List[Dict[str, object]],
    canonical_name: str,
    name: str,
    fallback_person: str,
    allow_geocode: bool,
    birth_coord: Optional[Coord],
    death_coord: Optional[Coord],
    birth_loc: str,
    death_loc: str,
    birth_modern: str,
    death_modern: str,
    birth_date: str,
    death_date: str,
    coords_cache: Dict[str, Coord],
    coords_search_map: Dict[str, List[Tuple[float, float, float]]],
    event_callback: Optional[callable],
    parsed_doc: object,
    normalized_md: str,
    highlight_works: List[str],
    split_ancient_modern: Callable[..., Tuple[str, str]],
    fuzzy_coord_lookup: Callable[..., Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
) -> ProfileData:
    """Phase 6: final assembly — build locations, attach summaries, return profile."""
    loc_items = profile_location_utils.build_location_items(
        profile_location_utils.LocationBuildContext(
            locations=locations, coords_cache=coords_cache,
            coords_search_map=coords_search_map, person_name=name,
            fallback_person=fallback_person, allow_geocode=allow_geocode,
            event_callback=event_callback, split_ancient_modern=split_ancient_modern,
            fuzzy_coord_lookup=fuzzy_coord_lookup,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            resolve_place_coord=resolve_place_coord,
            extract_works=extract_works, split_quote_lines=split_quote_lines,
        )
    )
    if not loc_items:
        loc_items = profile_location_utils.build_fallback_location_items(
            coords_cache=coords_cache, birth_coord=birth_coord, death_coord=death_coord,
            birth_loc=birth_loc, death_loc=death_loc,
            birth_modern=birth_modern, death_modern=death_modern,
            birth_date=birth_date, death_date=death_date,
            split_ancient_modern=split_ancient_modern, event_callback=event_callback,
        )
    loc_items = profile_location_utils.collapse_sparse_single_site_locations(loc_items, extract_works=extract_works)
    loc_items = profile_location_utils.sort_profile_locations(loc_items)
    loc_items = _attach_location_posters(canonical_name, loc_items)
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
        "workTexts": extract_work_texts(normalized_md),
        "workSummaries": _collect_profile_work_summaries(
            normalized_md=normalized_md, person_name=canonical_name,
            highlight_works=highlight_works, locations=loc_items,
        ),
    }


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
    build_points_fn: Callable[..., List[dict]],
) -> Optional[ProfileData]:
    if not isinstance(md, str) or not md.strip():
        return None

    # ── Phase 1: parse markdown ──
    parsed_doc, info, locations, coords_cache, coords_search_map, normalized_md = (
        _parse_md_and_fallback_info(md)
    )
    if not info and not locations:
        return None

    fallback_person = str(fallback_person or "").strip()
    name_raw = str(info.get("姓名", "") or fallback_person).strip()

    # ── Phase 2: resolve identity ──
    canonical_name, name, title, description, works, short_review = (
        _resolve_person_name_and_summary(
            name_raw=name_raw,
            fallback_person=fallback_person,
            info=info,
            description=parsed_doc.overview,
            locations=locations,
            normalized_md=normalized_md,
            work_texts=extract_work_texts(normalized_md),
            parsed_doc=parsed_doc,
        )
    )

    # ── Phase 3: life events ──
    birth_text = info.get("出生", "")
    death_text = info.get("去世", "")
    birth_date, birth_loc, birth_geocode_loc = parser_utils.parse_date_location_details(
        birth_text, ["出生于", "生于"]
    )
    death_date, death_loc, death_geocode_loc = parser_utils.parse_date_location_details(
        death_text, ["卒于", "去世于", "卒"]
    )

    # ── Phase 3b: fallback locations ──
    locations = _resolve_fallback_locations(
        locations, parsed_doc, build_points_fn,
        allow_geocode=allow_geocode, event_callback=event_callback,
    )

    # ── Phase 3c: Xu Xiake candidates ──
    person_key = canonical_name or fallback_person
    locations = _inject_xu_xiake_candidates(person_key, name_raw, locations)

    # ── Phase 4: coords ──
    birth_text = info.get("出生", "")
    death_text = info.get("去世", "")
    loc_texts = [birth_loc, death_loc]
    loc_texts.extend([loc.get("location") or loc.get("name") or "" for loc in locations])
    batch_split_ancient_modern(loc_texts, event_callback=event_callback)
    birth_modern = split_ancient_modern(birth_geocode_loc or birth_loc, event_callback)[1]
    death_modern = split_ancient_modern(death_geocode_loc or death_loc, event_callback)[1]
    birth_coord = profile_location_utils.resolve_life_event_coord(
        raw_text=birth_text, raw_loc=birth_loc, geocode_loc=birth_geocode_loc,
        modern_loc=birth_modern, coords_cache=coords_cache,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord, allow_geocode=allow_geocode,
    )
    death_coord = profile_location_utils.resolve_life_event_coord(
        raw_text=death_text, raw_loc=death_loc, geocode_loc=death_geocode_loc,
        modern_loc=death_modern, coords_cache=coords_cache,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord, allow_geocode=allow_geocode,
    )

    # ── Phase 5: person record ──
    person = _assemble_person_record(
        canonical_name=canonical_name, name=name, name_raw=name_raw,
        fallback_person=fallback_person, title=title, description=description,
        short_review=short_review, info=info, birth_loc=birth_loc,
        birth_date=birth_date, birth_coord=birth_coord, death_loc=death_loc,
        death_date=death_date, death_coord=death_coord, works=works,
        normalized_md=normalized_md, parsed_doc=parsed_doc,
    )

    # ── Phase 6: final assembly ──
    return _finalize_profile(
        person=person, locations=locations, canonical_name=canonical_name,
        name=name, fallback_person=fallback_person, allow_geocode=allow_geocode,
        birth_coord=birth_coord, death_coord=death_coord, birth_loc=birth_loc,
        death_loc=death_loc, birth_modern=birth_modern, death_modern=death_modern,
        birth_date=birth_date, death_date=death_date, coords_cache=coords_cache,
        coords_search_map=coords_search_map, event_callback=event_callback,
        parsed_doc=parsed_doc, normalized_md=normalized_md,
        highlight_works=_sanitize_person_works(
            canonical_name,
            _merge_unique_strings(
                _merge_person_summary_overrides(canonical_name, _get_person_summary_item(canonical_name)).get("works") or [],
                works,
            ),
        ),
        split_ancient_modern=split_ancient_modern,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
    )


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
    build_points_fn: Callable[..., List[dict]],
) -> Optional[ProfileData]:
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
