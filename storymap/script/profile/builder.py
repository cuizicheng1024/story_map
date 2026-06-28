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


_FOREIGN_ALIAS_PATH = data_corpus_file_path("foreign_name_aliases.json")
_FOREIGN_ALIAS_CACHE: Dict[str, Dict[str, str]] = {}
_FOREIGN_ALIAS_LOADED = False


def _load_foreign_aliases() -> Dict[str, Dict[str, str]]:
    global _FOREIGN_ALIAS_LOADED
    if _FOREIGN_ALIAS_LOADED:
        return _FOREIGN_ALIAS_CACHE
    _FOREIGN_ALIAS_LOADED = True
    try:
        payload = json.loads(_FOREIGN_ALIAS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _FOREIGN_ALIAS_CACHE
    entries = payload.get("entries") if isinstance(payload, dict) else {}
    if isinstance(entries, dict):
        for key, value in entries.items():
            if isinstance(value, dict):
                _FOREIGN_ALIAS_CACHE[str(key).strip()] = {
                    str(k).strip(): str(v).strip()
                    for k, v in value.items()
                    if isinstance(v, (str, int, float))
                }
    return _FOREIGN_ALIAS_CACHE


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


_LOCATION_POSTER_OVERRIDES: Dict[str, Dict[str, Dict[str, str]]] = {
    "梁思成": {
        "五台山佛光寺": {
            "png": "https://upload.wikimedia.org/wikipedia/commons/c/c6/Foguang_Temple_9.JPG"
        }
    }
}


def _attach_location_posters(person_name: str, locations: List[Dict[str, object]]) -> List[Dict[str, object]]:
    overrides = _LOCATION_POSTER_OVERRIDES.get(str(person_name or "").strip()) or {}
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


_PERSON_WORK_EXCLUSIONS = {
    "关羽": {"三国演义"},
    "诸葛亮": {"三国演义"},
    "班固": {"史记"},
    "纪昀": {"聊斋志异"},
    "董仲舒": {"春秋"},
    "孟子": {"诗", "书", "诗经", "书经"},
    "孟子，名轲": {"诗", "书", "诗经", "书经"},
    "周敦颐": {"周易"},
    "陈寿": {"三国志"},
    "郦道元": {"水经"},
    "闻一多": {"周易", "诗经", "庄子", "楚辞"},
    "张思德": {"为人民服务"},
    "严复": {"国闻报"},
    "列宁": {"火星报"},
    "弗拉基米尔·列宁": {"火星报"},
    "弗拉基米尔·伊里奇·乌里扬诺夫": {"火星报"},
    "袁鹰": {"人民日报"},
    "陆定一": {"红星", "解放日报"},
    "康有为": {"马关条约"},
    "希特勒": {"凡尔赛条约"},
    "阿道夫·希特勒": {"凡尔赛条约"},
    "刘少奇": {"中国土地法大纲", "土地改革法", "中华人民共和国土地改革法"},
    "华盛顿": {"美利坚合众国宪法", "美国宪法"},
    "乔治·华盛顿": {"美利坚合众国宪法", "美国宪法"},
    "马丁·路德": {"圣经"},
    "李世民": {"氏族志", "贞观律"},
    "利玛窦": {"几何原本"},
    "大卫·劳合·乔治": {"凡尔赛和约", "国民保险法", "人民代表法"},
    "劳合·乔治": {"凡尔赛和约", "国民保险法", "人民代表法"},
    "姚鼐": {"四库全书"},
    "孔丘": {"论语"},
    "孔子": {"论语"},
    "叶圣陶": {"小说月报"},
    "玄奘": {"大般若经", "瑜伽师地论"},
    "杜牧": {"孙子兵法"},
    "康熙": {"古今图书集成", "康熙字典", "尼布楚条约"},
    "康熙帝": {"古今图书集成", "康熙字典", "尼布楚条约"},
    "爱新觉罗·玄烨": {"古今图书集成", "康熙字典", "尼布楚条约"},
    "江竹筠": {"挺进报", "红岩"},
    "瞿秋白": {"晨报"},
    "陈独秀": {"新青年"},
    "陈韪": {"三国志"},
    "贾宪": {"九章算术"},
    "陈伯达": {"红旗"},
    "阿沛·阿旺晋美": {"十七条协议", "关于和平解放西藏办法的协议"},
    "崔融": {"三教珠英"},
    "卓文君": {"白头吟"},
    "孙膑": {"史记", "史记·孙子吴起列传", "齐孙子"},
    "蔡文姬": {"胡笳十八拍"},
    "姚文元": {"海瑞罢官"},
}


_PERSON_PREFERRED_WORKS = {
    "列宁": ["帝国主义是资本主义的最高阶段", "国家与革命"],
    "弗拉基米尔·伊里奇·乌里扬诺夫": ["帝国主义是资本主义的最高阶段", "国家与革命"],
    "刘少奇": ["论共产党员的修养"],
    "希特勒": ["我的奋斗"],
    "阿道夫·希特勒": ["我的奋斗"],
    "康有为": ["新学伪经考", "孔子改制考", "大同书"],
    "瞿秋白": ["赤都心史", "饿乡纪程"],
    "陈独秀": ["敬告青年"],
    "孙膑": ["孙膑兵法"],
}


_PERSON_ACHIEVEMENT_REPLACEMENTS = {
    "方志敏": {
        "创立中国工农红军第十军团": "创建中国工农红军第十军，并在红十军团成立后担任重要领导职务",
    },
    "常遇春": {
        "鄱阳湖之战俘获陈友谅": "鄱阳湖之战重创陈友谅部，陈友谅最终败亡",
    },
}


_PERSON_SUMMARY_OVERRIDES = {
    "孙膑": {
        "spotlight": "战国时期齐国军事家，因桂陵、马陵之战而名扬后世。",
        "intro": "战国时期齐国军事家，因桂陵、马陵之战而名扬后世。",
        "short_review": "辅佐田忌，策划桂陵、马陵之战，是中国古代兵家思想的重要代表人物之一。",
        "status": "战国时期著名军事家，因桂陵、马陵之战而名扬后世，是中国古代兵家思想的重要代表人物之一。",
        "identities": "军事家、兵家代表人物、齐国军师",
        "achievements": "辅佐田忌，策划桂陵之战大败魏军；在马陵之战中以减灶之计诱敌深入，重创魏军；相传著有《孙膑兵法》，承继并发展孙武军事思想。",
        "works": ["孙膑兵法"],
    },
    "蔡文姬": {
        "short_review": "创作《悲愤诗》二首，为中国早期文人五言、骚体长篇叙事诗代表作。",
        "achievements": "继承家学，博通经史音律，长于诗文、书法与琴艺；创作《悲愤诗》二首，为中国早期文人五言、骚体长篇叙事诗代表作；《胡笳十八拍》历来多附会于蔡文姬名下，作者归属存疑；默写其父蔡邕所藏典籍四百余篇，为保存汉代文献做出贡献",
        "works": ["悲愤诗"],
    },
}


_PERSON_WORK_SUMMARY_OVERRIDES = {
    ("孙膑", "孙膑兵法"): {
        "title": "孙膑兵法",
        "authors": ["孙膑"],
        "related_people": ["孙膑"],
        "source_pages": ["孙膑"],
        "era": "战国",
        "genre": "兵书",
        "one_liner": "相传为孙膑所撰或整理的兵书，继承并发展了先秦兵家思想。",
        "summary": "相传为孙膑所撰或整理的兵书，继承并发展了先秦兵家思想。",
        "quote": "今本《孙膑兵法》系银雀山汉墓竹简出土后重见天日，其具体成书情况与作者归属仍有讨论。",
        "quotes": [
            "今本《孙膑兵法》系银雀山汉墓竹简出土后重见天日，其具体成书情况与作者归属仍有讨论。"
        ],
        "quote_policy": "preferred",
    },
    ("蔡文姬", "悲愤诗"): {
        "title": "悲愤诗",
        "authors": ["蔡文姬"],
        "related_people": ["蔡文姬"],
        "source_pages": ["蔡文姬"],
        "era": "东汉末年",
        "genre": "诗",
        "one_liner": "现存较能确定归于蔡文姬名下的代表作品，为中国早期文人叙事诗的重要篇章。",
        "summary": "现存较能确定归于蔡文姬名下的代表作品，为中国早期文人叙事诗的重要篇章。",
        "quote": "现存较能确定归于她名下的作品主要是《悲愤诗》二首。",
        "quotes": ["现存较能确定归于她名下的作品主要是《悲愤诗》二首。"],
        "quote_policy": "preferred",
    },
}


def _filter_person_works(person_name: str, works: List[str]) -> List[str]:
    exclusions = _PERSON_WORK_EXCLUSIONS.get(str(person_name or "").strip(), set())
    if not exclusions:
        return works
    return [title for title in works if str(title or "").strip() not in exclusions]


def _sanitize_person_works(person_name: str, works: List[str]) -> List[str]:
    name = str(person_name or "").strip()
    filtered = _filter_person_works(name, list(works or []))
    preferred = _PERSON_PREFERRED_WORKS.get(name) or []
    return _merge_unique_strings(filtered, preferred)


def _normalize_person_achievements(person_name: str, achievements: str) -> str:
    text = str(achievements or "").strip()
    replacements = _PERSON_ACHIEVEMENT_REPLACEMENTS.get(str(person_name or "").strip()) or {}
    for source, target in replacements.items():
        if source:
            text = text.replace(source, target)
    return text


def _merge_person_summary_overrides(person_name: str, summary: Dict[str, object]) -> Dict[str, object]:
    merged = dict(summary or {})
    overrides = _PERSON_SUMMARY_OVERRIDES.get(str(person_name or "").strip()) or {}
    if overrides:
        merged.update(overrides)
    return merged


def _apply_person_work_summary_override(
    person_name: str,
    title: str,
    item: Dict[str, object],
) -> Dict[str, object]:
    merged = dict(item or {})
    overrides = _PERSON_WORK_SUMMARY_OVERRIDES.get((str(person_name or "").strip(), str(title or "").strip())) or {}
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
    name_raw = str(info.get("姓名", "") or fallback_person).strip()
    canonical_name = name_raw.split("（", 1)[0].strip() or name_raw
    name = name_raw or canonical_name
    summary = _merge_person_summary_overrides(canonical_name, _get_person_summary_item(canonical_name))
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
    works = _sanitize_person_works(canonical_name, works)
    work_texts = extract_work_texts(normalized_md)
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

    person_key = canonical_name or fallback_person
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
    native_place = parser_utils._extract_native_place_from_story_text(
        normalized_md,
        basic_info_map=info,
        overview=description,
    )
    highlight_status = str(summary.get("status") or info.get("历史地位", "") or "").strip()
    highlight_identities = str(summary.get("identities") or info.get("主要身份", "") or "").strip()
    highlight_achievements = _normalize_person_achievements(
        canonical_name,
        str(summary.get("achievements") or info.get("主要成就", "") or "").strip(),
    )
    highlight_works = _sanitize_person_works(canonical_name, _merge_unique_strings(summary.get("works") or [], works))
    summary_reviews = summary.get("reviews")
    if not isinstance(summary_reviews, list):
        summary_reviews = []
    highlight_reviews = _merge_unique_strings(summary_reviews, parsed_doc.historical_reviews)
    courtesy_name = str(info.get("字", "") or info.get("表字", "")).strip()
    art_name = str(info.get("号", "") or info.get("别号", "")).strip()
    # When the source markdown writes the courtesy / art name in the
    # `**姓名**` field (e.g. "王勃（字子安）") instead of using the
    # dedicated `**字**` field, fall back to the parenthetical so it
    # can still be surfaced in the introduction subtitle below the
    # heading.
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
        info.get("别名", ""),
        info.get("别称", ""),
        info.get("曾用名", ""),
        info.get("又名", ""),
        courtesy_name,
        art_name,
    )
    foreign_name = str(info.get("外文名", "") or info.get("外文", "")).strip()
    if not foreign_name:
        foreign_name, foreign_country, foreign_country_zh = _lookup_foreign_alias(name)
    else:
        foreign_country = str(info.get("外文国家", "")).strip()
        foreign_country_zh = str(info.get("国家", "")).strip()
    person = {
        # Strip the parenthetical courtesy / art name from the display
        # name so the heading only shows the person's actual name
        # (e.g. "王勃" instead of "王勃（字子安）"). The courtesy name
        # is preserved separately as courtesyName and can be rendered
        # in the introduction subtitle below the heading.
        "name": canonical_name or "人物",
        "nameRaw": name,
        "foreignName": foreign_name,
        "foreignCountry": foreign_country,
        "foreignCountryZh": foreign_country_zh,
        "title": title,
        "description": description,
        "quote": short_review or title,
        "shortReview": short_review or title,
        "dynasty": dynasty,
        "courtesyName": courtesy_name,
        "artName": art_name,
        "aliases": aliases,
        "birthplace": birth_loc,
        "nativePlace": native_place,
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
    loc_items = _attach_location_posters(canonical_name, loc_items)
    work_summaries = _collect_profile_work_summaries(
        normalized_md=normalized_md,
        person_name=canonical_name,
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
