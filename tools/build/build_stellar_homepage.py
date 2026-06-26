#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen

from storymap.script.core.project_paths import (
    data_corpus_file_path,
    data_corpus_dir_path,
    data_reports_dir_path,
    is_valid_person_name,
    person_name_from_filename,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
    story_person_names,
)
from storymap.script.core.person_registry import canonical_story_name_entries as registry_canonical_story_name_entries, person_redirects
from storymap.script.core.analytics import analytics_head_html
from storymap.script.profile.tooltip_js import person_tooltip_js
from storymap.script.core.build_meta import build_artifact_meta
from storymap.script.core import parsers as parser_utils

try:
    from tools.build.homepage_search import HAS_PINYIN, build_search_fields
except Exception:
    try:
        from tools.homepage_search import HAS_PINYIN, build_search_fields
    except Exception:
        from homepage_search import HAS_PINYIN, build_search_fields

try:
    from tools.build.sync_star_office_ui import sync_star_office_ui as _sync_orange_office_ui_impl
except Exception:
    try:
        from tools.sync_star_office_ui import sync_star_office_ui as _sync_orange_office_ui_impl
    except Exception:
        _sync_orange_office_ui_impl = None


REPO_ROOT = project_root_path()
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
try:
    from storymap.script.core.env_utils import apply_story_map_env_aliases, env_flag
    from storymap.script.profile.graph_service import (
        graph_backend_name,
        load_home_graph_payload_with_source,
        should_sync_to_neo4j,
        sync_graph_payload_to_neo4j,
        write_normalized_graph_json,
    )
except Exception:
    apply_story_map_env_aliases = None
    env_flag = None
    graph_backend_name = None
    load_home_graph_payload_with_source = None
    should_sync_to_neo4j = None
    sync_graph_payload_to_neo4j = None
    write_normalized_graph_json = None
if load_dotenv:
    load_dotenv(dotenv_path=str((REPO_ROOT / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT.parent / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT / "data" / ".env").resolve()))
if apply_story_map_env_aliases:
    apply_story_map_env_aliases()
STORY_MD_DIR = story_md_dir_path()
STORY_MAP_DIR = story_artifacts_dir_path()
GRAPH_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "graph"
DATA_CORPUS_DIR = data_corpus_dir_path()
DATA_REPORTS_DIR = data_reports_dir_path()
SUMMARY_INDEX_JSON = data_corpus_file_path("people_summary_index.json")
WORK_SUMMARY_INDEX_JSON = data_corpus_file_path("work_summary_index.json")
KNOWLEDGE_GRAPH_JSON = data_corpus_file_path("people_knowledge_graph.json")
BIRTH_COORDS_WGS84_JSON = data_corpus_file_path("people_birth_coords_wgs84.json")
HOMEPAGE_PET_ASSET_OUTPUT_NAME = "orange.png"
HOMEPAGE_PET_ASSET_CANDIDATES = [
    REPO_ROOT / "assets" / "orange.png",
    REPO_ROOT / "tools" / "orange.png",
    REPO_ROOT / "orange.png",
    REPO_ROOT / "orange.PNG",
    REPO_ROOT / "tools" / "orange-avatar.png",
    REPO_ROOT / "orange-avatar.png",
]
HOME_DETAIL_NODE_FIELDS: Tuple[str, ...] = (
    "review",
    "work_summaries",
    "relations",
    "relations_meta",
    "domain_tags",
    "risk_level",
    "audit_pass",
    "audit_uncertain",
)
MIN_YEAR = -800
MAX_YEAR = 2000
ROLE_BAND_SPECS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("military", "军事", ("军事家", "兵家", "将领", "将军", "武将", "统帅", "元帅", "名将", "军人", "起义军领袖")),
    ("politics", "政治", ("政治家", "改革家", "革命家", "外交家", "领袖", "君主", "帝王", "皇帝", "总统", "丞相", "宰相", "大臣", "官员", "赞普", "首领")),
    ("literature", "文学", ("文学家", "诗人", "词人", "作家", "文豪", "散文家", "小说家", "剧作家", "文人", "辞赋家", "翻译家")),
    ("academic", "学术思想", ("哲学家", "教育家", "史学家", "历史学家", "学者", "理学家", "儒学家", "经学家", "古文字学家", "考古学家", "思想史家")),
    ("thought", "思想", ("思想家", "宗教家", "社会活动家", "启蒙思想家", "理论家", "法家代表人物")),
    ("science", "科学", ("科学家", "数学家", "物理学家", "化学家", "生物学家", "医学家", "医家", "发明家", "工程师", "农学家", "天文学家", "地理学家", "地质学家")),
    ("art", "艺术", ("艺术家", "画家", "书法家", "音乐家", "戏剧家", "戏曲家", "建筑师", "雕塑家", "设计师")),
]
ROLE_BAND_ORDER: List[str] = [item[0] for item in ROLE_BAND_SPECS] + ["other"]
ROLE_BAND_LABELS: Dict[str, str] = {key: label for key, label, _ in ROLE_BAND_SPECS}
ROLE_BAND_LABELS["other"] = "其他"
PERSON_PAGE_REDIRECTS: Dict[str, str] = person_redirects()


def _canonical_story_name_entries(raw_names: List[str]) -> List[Tuple[str, str, List[str]]]:
    return registry_canonical_story_name_entries(raw_names)


def _design_tokens_style_tag() -> str:
    css_path = REPO_ROOT / "storymap" / "script" / "profile" / "templates" / "design_tokens.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return f"<style>\n{css}\n</style>"


def _remove_person_alias_redirect_pages(story_map_dir: Path, redirects: dict[str, str]) -> None:
    for alias, canonical in (redirects or {}).items():
        alias_name = str(alias or "").strip()
        canonical_name = str(canonical or "").strip()
        if not alias_name or not canonical_name or alias_name == canonical_name:
            continue
        try:
            alias_path = Path(story_map_dir) / f"{alias_name}.html"
            if alias_path.exists():
                alias_path.unlink()
        except Exception:
            continue

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _build_payload_meta() -> Dict[str, object]:
    return build_artifact_meta(component="stellar_homepage", build_at=_now().replace(" ", "T"))


def _analytics_head_html() -> str:
    return analytics_head_html(page_type="homepage", page_name="人类群星闪耀时")


def _runtime_api_base_env() -> str:
    api_base = str(os.getenv("MAP_STORY_API_BASE", "")).strip()
    if "legacy.example" in api_base.lower():
        return ""
    return api_base


def _is_inside_china(lat: float, lng: float) -> bool:
    return 17.5 <= lat <= 55.5 and 72.0 <= lng <= 136.5


_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def _wgs84_to_gcj02(lat: float, lng: float) -> Tuple[float, float]:
    if not _is_inside_china(lat, lng):
        return lat, lng
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * _PI
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / (((_A * (1 - _EE)) / (magic * sqrt_magic)) * _PI)
    d_lng = (d_lng * 180.0) / ((_A / sqrt_magic) * math.cos(rad_lat) * _PI)
    return lat + d_lat, lng + d_lng


def _gcj02_to_wgs84(lat: float, lng: float) -> Tuple[float, float]:
    if not _is_inside_china(lat, lng):
        return lat, lng
    mg_lat, mg_lng = _wgs84_to_gcj02(lat, lng)
    return lat * 2.0 - mg_lat, lng * 2.0 - mg_lng


def _sha1_int(s: str) -> int:
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:12], 16)

@dataclass
class HtmlEntry:
    person: str
    file: str
    mtime: float


def _html_birth_has_coords(html_path: Path) -> bool:
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    m = re.search(r"\"birth\"\\s*:\\s*\\{([\\s\\S]*?)\\}\\s*,\\s*\"death\"", text)
    if not m:
        m = re.search(r"\"birth\"\\s*:\\s*\\{([\\s\\S]*?)\\}", text)
    if not m:
        return False
    body = m.group(1)
    return bool(re.search(r"\"lat\"\\s*:\\s*-?\\d+(?:\\.\\d+)?", body) and re.search(r"\"lng\"\\s*:\\s*-?\\d+(?:\\.\\d+)?", body))


def _scan_latest_html(story_map_dir: Path) -> Dict[str, HtmlEntry]:
    latest: Dict[str, HtmlEntry] = {}
    for p in story_map_dir.glob("*.html"):
        if not p.is_file():
            continue
        person = person_name_from_filename(p.name).strip()
        if not is_valid_person_name(person):
            continue
        e = HtmlEntry(person=person, file=p.name, mtime=p.stat().st_mtime)
        cur = latest.get(person)
        if cur is None:
            latest[person] = e
            continue
        cur_has = _html_birth_has_coords(story_map_dir / cur.file)
        e_has = _html_birth_has_coords(p)
        if e_has and not cur_has:
            latest[person] = e
            continue
        canonical_name = f"{person}.html"
        if e_has == cur_has:
            cur_is_canonical = cur.file == canonical_name
            e_is_canonical = e.file == canonical_name
            if e_is_canonical and not cur_is_canonical:
                latest[person] = e
                continue
        if e_has == cur_has and e.mtime > cur.mtime:
            latest[person] = e
    return latest


def _extract_birth_from_story_map_html(html_path: Path) -> Tuple[Optional[float], Optional[float], str, str]:
    try:
        text = html_path.read_text(encoding="utf-8")
    except Exception:
        return None, None, "", ""
    m = re.search(r"const data\s*=\s*(\{[\s\S]*?\})\s*;\s*window\.__EXPORT_DATA__", text)
    if not m:
        return None, None, "", ""
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None, None, "", ""
    person = data.get("person") if isinstance(data, dict) else None
    if not isinstance(person, dict):
        return None, None, "", ""
    dynasty = str(person.get("dynasty") or "").strip()
    birthplace = str(person.get("birthplace") or "").strip()
    birth = person.get("birth")
    if not isinstance(birth, dict):
        return None, None, birthplace, dynasty
    lat = birth.get("lat")
    lng = birth.get("lng")
    try:
        lat_f = float(lat) if lat is not None else None
    except Exception:
        lat_f = None
    try:
        lng_f = float(lng) if lng is not None else None
    except Exception:
        lng_f = None
    return lat_f, lng_f, birthplace, dynasty


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_people_from_story_md(story_md_dir: Path) -> List[str]:
    return story_person_names(story_md_dir)


def _extract_years_from_md(md_text: str) -> Tuple[Optional[int], Optional[int]]:
    text = md_text

    def parse_years(s: str) -> List[int]:
        out: List[int] = []
        src = str(s or "")
        for m in re.finditer(r"(?<!\d)(-?\d{1,4})(?!\d)", src):
            try:
                y = int(m.group(1))
            except Exception:
                continue
            if y < 0:
                out.append(y)
                continue
            suffix = src[m.end() : min(len(src), m.end() + 4)]
            if suffix.startswith("世纪"):
                continue
            if suffix and suffix[0] in ("月", "日", "号"):
                continue
            prefix = src[max(0, m.start() - 8) : m.start()]
            p = prefix.strip()
            if "公元前" in prefix or p.endswith("前") or "BC" in prefix.upper():
                y = -y
            out.append(y)
        return out

    def pick_year(s: str) -> Optional[int]:
        ys = parse_years(s)
        if not ys:
            return None
        return ys[0]

    def pick_two_years(s: str) -> Tuple[Optional[int], Optional[int]]:
        ys = parse_years(s)
        if len(ys) < 2:
            return None, None
        return ys[0], ys[1]

    m = re.search(r"\*\*生卒年\*\*[:：]\s*([^\n]+)", text)
    if not m:
        m = re.search(r"(?:生卒年|生卒)[:：]\s*([^\n]+)", text)
    if m:
        b, d = pick_two_years(m.group(1))
        if b is not None or d is not None:
            return b, d

    birth = None
    death = None
    mb = re.search(r"\*\*出生\*\*[:：]\s*([^\n]+)", text)
    if not mb:
        mb = re.search(r"(?:出生)[:：]\s*([^\n]+)", text)
    if mb:
        birth = pick_year(mb.group(1))

    md = re.search(r"\*\*(去世|逝世)\*\*[:：]\s*([^\n]+)", text)
    if not md:
        md = re.search(r"(去世|逝世)[:：]\s*([^\n]+)", text)
    if md:
        death = pick_year(md.group(2))

    if birth is None and death is None:
        head = text[:420]
        ys: List[int] = []
        for m in re.finditer(r"(公元前|公元|前)\s*(\d{1,4})\s*年", head):
            try:
                y = int(m.group(2))
            except Exception:
                continue
            prefix = m.group(1) or ""
            if prefix in ("公元前", "前"):
                y = -y
            ys.append(y)
        if len(ys) >= 2:
            return ys[0], ys[1]
        if len(ys) == 1:
            return ys[0], None

    if birth is not None and death is not None:
        try:
            if birth > death and birth > 1000 and death > 0 and death < 400:
                death = None
        except Exception:
            pass

    return birth, death


def _extract_birthplace_from_md(md_text: str) -> Tuple[str, str, str]:
    if not isinstance(md_text, str) or not md_text.strip():
        return "", "", ""
    m = re.search(r"\*\*出生\*\*[:：]\s*([^\n]+)", md_text)
    if not m:
        m = re.search(r"(?:出生)[:：]\s*([^\n]+)", md_text)
    if not m:
        head = md_text[:320]
        mm = re.search(r"([^\s，,。]{2,18})人", head)
        if mm:
            cand = mm.group(1).strip()
            allow = [
                "北京",
                "天津",
                "上海",
                "重庆",
                "河北",
                "河南",
                "山东",
                "山西",
                "陕西",
                "江苏",
                "浙江",
                "安徽",
                "江西",
                "福建",
                "广东",
                "广西",
                "湖南",
                "湖北",
                "四川",
                "云南",
                "贵州",
                "甘肃",
                "青海",
                "辽宁",
                "吉林",
                "黑龙江",
                "内蒙古",
                "宁夏",
                "新疆",
                "西藏",
                "海南",
                "香港",
                "澳门",
            ]
            if any(x in cand for x in allow) or re.search(r"(省|市|县|州|郡|国|府|区|镇|乡|村)$", cand):
                return cand, cand, ""
        return "", "", ""
    text = m.group(1).strip()
    if not re.search(r"(一说|或说|又说|另说)", text):
        text = re.sub(
            r"[（(][^）)]*(存疑|不详|未详|未知|无法确认|生年不详|卒年不详)[^）)]*[）)]\s*$",
            "",
            text,
        ).strip()
    text = _strip_birthplace_date_ambiguity_text(text)
    text = re.sub(
        r"^\s*(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?\s*[?？]?\s*[，,]?\s*",
        "",
        text,
    ).strip()
    text = re.sub(
        r"^\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?\s*[?？]?\s*[，,]?\s*",
        "",
        text,
    ).strip()
    text = re.sub(r"^\s*\d{1,2}\s*(?:日|号)\s*[?？]?\s*[，,]?\s*", "", text).strip()
    text = re.sub(r"^\s*(?:约|大约|约于)?\s*\d{1,2}\s*世纪(?:初|中|末)?\s*[，,]?\s*", "", text).strip()
    if parser_utils._location_text_is_native_place_only(parser_utils._strip_common_birthplace_prefixes(text)):
        return "", "", ""
    if not text:
        return "", "", ""
    if re.fullmatch(
        r"(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?\s*",
        text,
    ):
        return "", "", ""
    if re.fullmatch(r"\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?\s*", text):
        return "", "", ""
    parts = [p.strip() for p in re.split(r"[，,]", text) if p.strip()]
    bad = re.compile(r"(存疑|不详|未详|未知|无法确认|生年不详|卒年不详|一说|或说|又说|另说|另有|说法|年说)")
    loc = ""
    for p in parts:
        if not p or bad.search(p):
            continue
        if _looks_like_date_or_period_text(p):
            continue
        if re.search(r"(年间|时期|时代|初年|末年|前期|中期|后期)$", p) and not re.search(
            r"(省|市|县|州|郡|国|府|区|镇|乡|村|岛|湾|山|河|湖|海)",
            p,
        ):
            continue
        loc = p
        break
    if not loc:
        loc = parts[0] if parts else text
    loc = parser_utils._strip_native_place_annotations(loc.strip())
    loc = re.sub(r"^\s*(?:出生于|出生在|生于|生在|于|在)\s*", "", loc).strip()
    if (loc.startswith("（") and loc.endswith("）")) or (loc.startswith("(") and loc.endswith(")")):
        loc = loc[1:-1].strip()
    if not loc:
        return "", "", ""
    bad_kw = re.compile(r"(小说|虚构|未明确|具体年份|年份|生年|卒年|出生年|出生年份|年号)")
    if bad_kw.search(loc):
        return "", "", ""
    if re.search(r"(公元前|公元)\s*\d{1,4}", loc):
        return "", "", ""
    if re.search(r"\d{2,4}\s*年", loc):
        return "", "", ""
    if re.search(r"[一二三四五六七八九十]{1,4}年", loc) and not re.search(r"(省|市|县|州|郡|国|府|区|镇|乡|村|岛|湾|山|河|湖|海)", loc):
        return "", "", ""
    ancient = loc
    modern = ""
    if "（" in loc and "）" in loc:
        left, right = loc.split("（", 1)
        ancient = left.strip()
        modern = right.split("）", 1)[0].strip()
    elif "(" in loc and ")" in loc:
        left, right = loc.split("(", 1)
        ancient = left.strip()
        modern = right.split(")", 1)[0].strip()
    modern = re.sub(r"^今", "", modern).strip()
    loc = re.sub(r"[（）()]+", "", loc).strip()
    ancient = re.sub(r"[（）()]+", "", ancient).strip()
    modern = re.sub(r"[（）()]+", "", modern).strip()
    loc = _strip_birthplace_date_ambiguity_text(loc)
    ancient = _strip_birthplace_date_ambiguity_text(ancient)
    modern = _strip_birthplace_date_ambiguity_text(modern)
    if _birthplace_has_multiple_place_options(loc):
        modern = ""
    return loc, ancient, modern


def _extract_basic_place_from_md(md_text: str, labels: Tuple[str, ...]) -> Tuple[str, str, str]:
    if not isinstance(md_text, str) or not md_text.strip():
        return "", "", ""
    match = None
    for label in labels:
        match = re.search(rf"\*\*{re.escape(label)}\*\*[:：]\s*([^\n]+)", md_text)
        if match:
            break
    raw = str(match.group(1) or "").strip() if match else ""
    if not raw:
        raw = parser_utils._extract_native_place_from_story_text(md_text)
    if not raw:
        return "", "", ""
    ancient = raw
    modern = ""
    bracket_match = re.match(r"^(.*?)[（(]([^）)]+)[）)]\s*$", raw)
    if bracket_match:
        ancient = str(bracket_match.group(1) or "").strip()
        modern = str(bracket_match.group(2) or "").strip()
    modern = re.sub(r"^今", "", modern).strip()
    raw = re.sub(r"[（）()]+", "", raw).strip()
    ancient = re.sub(r"[（）()]+", "", ancient).strip()
    modern = re.sub(r"[（）()]+", "", modern).strip()
    return raw, ancient, modern


def _looks_like_date_or_period_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"^\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?$", value):
        return True
    if re.search(
        r"^(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?$",
        value,
    ):
        return True
    if re.search(r"^(?:约|大约|约于)?\s*\d{1,2}\s*世纪(?:初|中|末)?$", value):
        return True
    return False


def _strip_parenthetical_place_text(text: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", str(text or "")).strip()


def _strip_common_birthplace_prefixes(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^今\s*", "", cleaned).strip()
    cleaned = re.sub(r"^(?:出生于|出生在|生于|生在|于|在)\s*", "", cleaned).strip()
    return cleaned


def _strip_birthplace_date_ambiguity_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"[（(][^（）()]*?(?:出生时辰|出生(?:具体)?日期|具体出生日期|一说生于\s*\d{3,4}\s*年)[^（）()]*?[）)]",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"(?:[，,]\s*)?(?:具体出生日期待考|出生具体日期说法不一|出生时辰有说法不一|一说生于\s*\d{3,4}\s*年)\s*$",
        "",
        cleaned,
    ).strip()
    return cleaned


def _birthplace_text_is_ambiguous(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"(存疑|不详|未详|未知|无法确认|待考|待查证|说法不一|一说|或说|又说|另说|另有)", value):
        return True
    if re.search(r"(有[^，。；]*或[^，。；]*(?:等|等说)?)", value):
        return True
    return False


def _birthplace_has_multiple_place_options(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"(有[^，。；]*或[^，。；]*(?:地|处|城|岛|州|郡|县|市|国|等)?)", value):
        return True
    if "或" not in value:
        return False
    return bool(re.search(r"(今[^，。；]*或)|(或[^，。；]*今)", value))


def _birthplace_source_values(birthplace_modern: str, birthplace_ancient: str, birthplace_raw: str) -> List[str]:
    if _birthplace_has_multiple_place_options(birthplace_raw):
        return []
    out: List[str] = []
    for value in (birthplace_modern, birthplace_ancient, birthplace_raw):
        text = str(value or "").strip()
        if not text or _birthplace_text_is_ambiguous(text):
            continue
        out.append(text)
    return out


def _birthplace_lookup_terms(birthplace_modern: str, birthplace_ancient: str, birthplace_raw: str) -> List[str]:
    terms: List[str] = []
    seen = set()
    for value in _birthplace_source_values(birthplace_modern, birthplace_ancient, birthplace_raw):
        cleaned = _strip_common_birthplace_prefixes(value)
        variants = [cleaned, _strip_parenthetical_place_text(cleaned)]
        for variant in variants:
            term = str(variant or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _extract_relations(md_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    text = md_text
    kw_norm = {
        "父": "父亲",
        "父亲": "父亲",
        "母": "母亲",
        "母亲": "母亲",
        "祖父": "祖父",
        "祖母": "祖母",
        "兄": "兄长",
        "兄长": "兄长",
        "弟": "弟弟",
        "弟弟": "弟弟",
        "姐": "姐姐",
        "姐姐": "姐姐",
        "妹": "妹妹",
        "妹妹": "妹妹",
        "子": "子女",
        "儿子": "子女",
        "女儿": "子女",
        "配偶": "配偶",
        "妻子": "配偶",
        "丈夫": "配偶",
        "师从": "师承",
        "师事": "师承",
        "老师": "师承",
        "导师": "师承",
        "友人": "亲友",
        "好友": "亲友",
        "朋友": "亲友",
        "同僚": "同僚",
        "同事": "同僚",
        "盟友": "盟友",
        "对手": "对手",
        "政敌": "政敌",
        "敌人": "政敌",
    }
    patterns: List[Tuple[str, str, int]] = [
        ("父亲", r"(父亲|父)[：:][^\S\n]*([^\n]+)", 2),
        ("母亲", r"(母亲|母)[：:][^\S\n]*([^\n]+)", 2),
        ("祖父", r"(祖父)[：:][^\S\n]*([^\n]+)", 2),
        ("祖母", r"(祖母)[：:][^\S\n]*([^\n]+)", 2),
        ("兄长", r"(兄长|兄)[：:][^\S\n]*([^\n]+)", 2),
        ("弟弟", r"(弟弟|弟)[：:][^\S\n]*([^\n]+)", 2),
        ("姐姐", r"(姐姐|姐)[：:][^\S\n]*([^\n]+)", 2),
        ("妹妹", r"(妹妹|妹)[：:][^\S\n]*([^\n]+)", 2),
        ("子女", r"(子|儿子|女儿)[：:][^\S\n]*([^\n]+)", 2),
        ("配偶", r"(配偶|妻子|丈夫)[：:][^\S\n]*([^\n]+)", 2),
        ("师承", r"(师从|师事|老师|导师)[：:][^\S\n]*([^\n]+)", 2),
        ("亲友", r"(友人|好友|朋友)[：:][^\S\n]*([^\n]+)", 2),
        ("同僚", r"(同僚|同事|盟友|对手|政敌|敌人)[：:][^\S\n]*([^\n]+)", 2),
        ("并称", r"与([^\n，。,。;；]{2,10})并称", 1),
        ("会面", r"与([^\n，。,。;；]{2,10})相会", 1),
        ("交友", r"结交([^\n，。,。;；]{2,10})", 1),
        ("问道", r"问道于([^\n，。,。;；]{2,10})", 1),
        ("问学", r"问学于([^\n，。,。;；]{2,10})", 1),
    ]
    out_meta: List[Dict[str, str]] = []
    seen_name = set()
    for default_label, pat, group_idx in patterns:
        for m in re.finditer(pat, text):
            label = default_label
            if group_idx == 2:
                kw = str(m.group(1) or "").strip()
                if kw:
                    label = kw_norm.get(kw, label)
            s = str(m.group(group_idx) or "").strip()
            if not s:
                continue
            s = re.sub(r"[，。；;].*$", "", s).strip()
            parts = re.split(r"[、,，/｜|]", s)
            for p in parts:
                n = re.sub(r"[\s\(\)（）\[\]【】《》<>\"“”‘’·•]+", "", p).strip()
                if not (1 < len(n) <= 10):
                    continue
                if n in seen_name:
                    continue
                seen_name.add(n)
                out_meta.append({"name": n, "label": label})
    names = [x["name"] for x in out_meta if isinstance(x, dict) and x.get("name")]
    return names[:8], out_meta[:12]


def _pick_markdown_field(md_text: str, field: str) -> str:
    text = md_text

    m = re.search(rf"\*\*{re.escape(field)}\*\*\s*[:：]\s*([^\n]+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(rf"^-\s*\*\*{re.escape(field)}\*\*\s*[:：]\s*([^\n]+)", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def _extract_disambiguation(md_text: str) -> Tuple[List[str], str, List[str]]:
    aliases: List[str] = []
    foreign = ""
    domains: List[str] = []

    alias_raw = [
        _pick_markdown_field(md_text, "别名"),
        _pick_markdown_field(md_text, "别名/称号"),
        _pick_markdown_field(md_text, "别名/字"),
        _pick_markdown_field(md_text, "又名"),
        _pick_markdown_field(md_text, "原名"),
        _pick_markdown_field(md_text, "号"),
    ]
    for a in [x for x in alias_raw if x]:
        parts = [p.strip() for p in re.split(r"[、,，/｜|；;]", a) if p.strip()]
        for p in parts:
            x = re.sub(r"^(原名|别名|别名/称号|别名/字|又名|号|字|笔名|曾用名|化名|小字|学名|谱名)[:：]?", "", p).strip()
            x = re.sub(r"[\[\]（）()“”\"'‘’\s·•]+", "", x).strip()
            if 1 < len(x) <= 16 and x not in aliases:
                aliases.append(x)
    foreign = (
        _pick_markdown_field(md_text, "外文名")
        or _pick_markdown_field(md_text, "英文名")
        or _pick_markdown_field(md_text, "原文名")
        or _pick_markdown_field(md_text, "外文名称")
        or ""
    )
    foreign = foreign.strip().strip("“”\"'‘’")
    d = (
        _pick_markdown_field(md_text, "领域标签")
        or _pick_markdown_field(md_text, "领域")
        or _pick_markdown_field(md_text, "学科")
        or _pick_markdown_field(md_text, "职业标签")
        or ""
    )
    if d:
        parts = [p.strip() for p in re.split(r"[、,，/｜|；;]", d) if p.strip()]
        for p in parts:
            x = re.sub(r"[\[\]（）()“”\"'‘’\s·•]+", "", p).strip()
            if 1 < len(x) <= 18 and x not in domains:
                domains.append(x)
    return aliases[:6], (foreign or ""), domains[:6]


def _split_role_parts(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts: List[str] = []
    for item in re.split(r"[、,，/｜|；;]", text):
        cleaned = str(item).strip()
        cleaned = re.sub(r"^(主要身份|身份|职业|职业标签|身份标签|领域标签|领域|学科)\s*[:：]?", "", cleaned).strip()
        cleaned = re.sub(r"[（(].*?[)）]", "", cleaned).strip()
        cleaned = re.sub(r"\s+", "", cleaned)
        if 1 < len(cleaned) <= 24 and cleaned not in parts:
            parts.append(cleaned)
    return parts


def _match_role_band(part: str) -> Optional[Tuple[str, str, str]]:
    value = str(part or "").strip()
    if not value:
        return None
    for band_key, band_label, keywords in ROLE_BAND_SPECS:
        for keyword in keywords:
            if keyword in value or value in keyword:
                return band_key, band_label, keyword
    return None


def _resolve_main_role_band(
    *,
    md_text: str,
    domain_tags: List[str],
    review: str,
    quote: str,
) -> Tuple[str, str]:
    explicit_parts: List[str] = []
    for field in ("主要身份", "身份", "职业", "身份标签", "职业标签", "领域标签", "领域", "学科"):
        explicit_parts.extend(_split_role_parts(_pick_markdown_field(md_text, field)))
    for item in domain_tags:
        explicit_parts.extend(_split_role_parts(item))
    seen: set[str] = set()
    for part in explicit_parts:
        if part in seen:
            continue
        seen.add(part)
        matched = _match_role_band(part)
        if matched:
            return matched[0], part

    fallback_text = " ".join([str(review or ""), str(quote or ""), str(md_text[:800] or "")]).strip()
    if fallback_text:
        best_score = 0
        best_band = "other"
        best_label = ROLE_BAND_LABELS["other"]
        for band_key, band_label, keywords in ROLE_BAND_SPECS:
            score = 0
            for keyword in keywords:
                score += fallback_text.count(keyword)
            if score > best_score:
                best_score = score
                best_band = band_key
                best_label = band_label
        if best_score > 0:
            return best_band, best_label
    return "other", ROLE_BAND_LABELS["other"]


def _dynasty_hint_from_md(md_text: str) -> str:
    m = re.search(r"\*\*时代\*\*[:：]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"时代[：:]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\*\*朝代\*\*[:：]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"朝代[：:]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    return ""


def _dynasty_mid_year(dynasty: str) -> Optional[int]:
    d = str(dynasty or "").strip()
    if not d:
        return None
    t = re.sub(r"\s+", "", d)

    ranges: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋", (-770, -476)),
        ("战国", (-475, -221)),
        ("春秋战国", (-770, -221)),
        ("先秦", (-800, -221)),
        ("秦", (-221, -206)),
        ("西汉", (-206, 8)),
        ("东汉", (25, 220)),
        ("汉", (-206, 220)),
        ("三国", (220, 280)),
        ("魏晋南北朝", (220, 589)),
        ("魏晋", (220, 420)),
        ("南北朝", (420, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("五代", (907, 960)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1911)),
        ("近代", (1840, 1911)),
        ("民国", (1912, 1949)),
        ("现代", (1949, 2000)),
        ("当代", (1949, 2000)),
    ]

    for key, (a, b) in ranges:
        if key and (key in t):
            return int(round((a + b) / 2))
    return None


def _pick_main_dynasty_by_years(birth_year: Optional[int], death_year: Optional[int]) -> str:
    by = birth_year if isinstance(birth_year, int) else None
    dy = death_year if isinstance(death_year, int) else None
    if by is None and dy is None:
        return ""
    if by is None:
        by = dy
    if dy is None:
        dy = by
    if by is None or dy is None:
        return ""
    a = min(by, dy)
    b = max(by, dy)
    if a == b:
        b = a + 1
    bands: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋战国", (-800, -221)),
        ("秦", (-221, -206)),
        ("汉", (-206, 220)),
        ("魏晋南北", (220, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1840)),
        ("近代", (1840, 1911)),
        ("现代", (1911, 2000)),
    ]
    best = ""
    best_ol = 0
    for name, (x, y) in bands:
        ol = max(0, min(b, y) - max(a, x))
        if ol > best_ol:
            best_ol = ol
            best = name
    return best


def _normalize_dynasty_label(*, person: str, dynasty_raw: str, birth_year: Optional[int], death_year: Optional[int]) -> str:
    s = str(dynasty_raw or "").strip()
    if s:
        return s
    overrides = {
        "李渊": "唐",
        "李世民": "唐",
        "唐太宗": "唐",
        "朱元璋": "明",
        "明太祖": "明",
    }
    if person in overrides:
        return overrides[person]
    return _pick_main_dynasty_by_years(birth_year, death_year) or ""


def _dynasty_range_from_label(dynasty: str) -> Optional[Tuple[int, int]]:
    d = str(dynasty or "").strip()
    if not d:
        return None
    t = re.sub(r"\s+", "", d)
    ranges: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋战国", (-800, -221)),
        ("先秦", (-800, -221)),
        ("秦", (-221, -206)),
        ("汉", (-206, 220)),
        ("魏晋南北", (220, 589)),
        ("魏晋", (220, 420)),
        ("南北朝", (420, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1911)),
        ("近代", (1840, 1911)),
        ("民国", (1912, 1949)),
        ("现代", (1911, 2000)),
        ("当代", (1911, 2000)),
    ]
    for key, (a, b) in ranges:
        if key and key in t:
            return a, b
    return None


def _pick_quote(spot: Dict[str, Any]) -> str:
    s = str(spot.get("spotlight") or "").strip()
    if s:
        return s
    quotes = spot.get("quotes")
    if isinstance(quotes, list) and quotes:
        q = str(quotes[0] or "").strip()
        if q:
            return q
    intro = str(spot.get("intro") or "").strip()
    if intro:
        return intro
    return ""


def _clean_review_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
    cleaned = re.sub(r"^(?:人物)?短评\s*[：:]\s*", "", cleaned)
    return cleaned.strip()


def _normalize_home_work_title(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[*_`]+", "", text)
    if text.startswith("《") and text.endswith("》") and len(text) > 2:
        text = text[1:-1]
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_work_titles_from_text(text: str, *, limit: int = 6) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in re.findall(r"《([^》]{1,40})》", str(text or "")):
        title = _normalize_home_work_title(raw)
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(title)
        if len(out) >= limit:
            break
    return out


def _resolve_person_works(spot: object, md_text: str, *, limit: int = 6) -> List[str]:
    if isinstance(spot, dict):
        raw_works = spot.get("works")
        if isinstance(raw_works, list):
            works: List[str] = []
            seen = set()
            for item in raw_works:
                title = _normalize_home_work_title(str(item or ""))
                if not title or title in seen:
                    continue
                seen.add(title)
                works.append(title)
                if len(works) >= limit:
                    return works
            if works:
                return works
    return _extract_work_titles_from_text(md_text, limit=limit)


def _load_work_summary_items(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return {}
    data = _read_json(path)
    items = data.get("items") if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in items.items():
        title = _normalize_home_work_title(str(key or ""))
        if not title or not isinstance(value, dict):
            continue
        item = dict(value)
        item["title"] = _normalize_home_work_title(str(item.get("title") or title))
        out[title] = item
        for alias in item.get("aliases") or []:
            alias_title = _normalize_home_work_title(str(alias or ""))
            if alias_title and alias_title not in out:
                out[alias_title] = item
    return out


def _pick_person_work_summaries(
    titles: List[str],
    work_summary_items: Dict[str, Dict[str, Any]],
    *,
    limit: int = 3,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw_title in titles:
        title = _normalize_home_work_title(raw_title)
        if not title or title in out:
            continue
        item = work_summary_items.get(title)
        if not isinstance(item, dict):
            continue
        out[title] = {
            "title": _normalize_home_work_title(str(item.get("title") or title)) or title,
            "authors": [str(x).strip() for x in item.get("authors") or [] if str(x).strip()],
            "era": str(item.get("era") or "").strip(),
            "genre": str(item.get("genre") or "").strip(),
            "one_liner": str(item.get("one_liner") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "quote": str(item.get("quote") or "").strip(),
            "quotes": [str(x).strip() for x in item.get("quotes") or [] if str(x).strip()],
            "quote_policy": str(item.get("quote_policy") or "").strip(),
        }
        if len(out) >= limit:
            break
    return out


_FOREIGN_PLACE_HINT_RE = re.compile(
    r"(美国|智利|法国|英国|俄罗斯|希腊|乌克兰|西班牙|意大利|德国|日本|韩国|朝鲜|越南|泰国|缅甸|斯里兰卡|印度尼西亚|印度|巴西|阿根廷|墨西哥|古巴|加拿大|澳大利亚|新西兰|南非|埃及|以色列|巴勒斯坦|土耳其|伊朗|伊拉克|叙利亚|阿富汗|巴基斯坦|挪威|瑞典|芬兰|丹麦|冰岛|荷兰|比利时|瑞士|奥地利|葡萄牙|波兰|捷克|匈牙利|罗马尼亚|保加利亚|塞尔维亚|克罗地亚|爱尔兰|苏联|黎巴嫩|哥伦比亚|尼泊尔|乌兹别克斯坦|土库曼斯坦|拉丁美洲|中亚|花拉子模|花剌子模|罗马|雅典|马其顿|佛罗伦萨|伦敦|巴黎|柏林|东京|都柏林|莫斯科)"
)
_DOMESTIC_PLACE_HINT_RE = re.compile(
    r"(中国|中华|北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|西藏|宁夏|新疆|香港|澳门|京师|汴京|临安|长安|洛阳|开封|应天府|顺天府|松江府|苏州府|杭州府|眉州|眉山|黄州|密州|徐州|常州|惠州|儋州|郡|府|州|县|省|市)"
)
_CHINESE_DYNASTY_HINT_RE = re.compile(
    r"(中国|中华|夏|商|周|春秋|战国|秦|汉|三国|魏|蜀汉|吴|晋|南北朝|隋|唐|宋|辽|金|元|明|清|民国|中国近代|中国现代|中国当代|近现代中国|当代中国)"
)
_FOREIGN_DYNASTY_HINT_RE = re.compile(
    r"(美国|智利|法国|英国|俄罗斯|希腊|乌克兰|西班牙|意大利|德国|日本|韩国|朝鲜|越南|泰国|缅甸|斯里兰卡|印度尼西亚|印度|巴西|阿根廷|墨西哥|古巴|加拿大|澳大利亚|新西兰|南非|埃及|以色列|巴勒斯坦|土耳其|伊朗|伊拉克|叙利亚|阿富汗|巴基斯坦|挪威|瑞典|芬兰|丹麦|冰岛|荷兰|比利时|瑞士|奥地利|葡萄牙|波兰|捷克|匈牙利|罗马尼亚|保加利亚|塞尔维亚|克罗地亚|爱尔兰|苏联|黎巴嫩|哥伦比亚|尼泊尔|乌兹别克斯坦|土库曼斯坦|拉丁美洲|中亚|古希腊|古罗马|罗马帝国|拜占庭|奥斯曼|波斯|阿拉伯|伊斯兰|阿拔斯|花拉子模|花剌子模|蒙兀儿|欧洲|欧洲近代|文艺复兴|启蒙|工业革命|维多利亚时代|托勒密王国|神圣罗马帝国|英属印度|法兰西|英格兰|苏格兰|马其顿|美索不达米亚)"
)


def _is_foreign_person(*, foreign_name: str, birthplace_modern: str, birthplace_raw: str, dynasty: str) -> bool:
    dynasty_text = str(dynasty or "").strip()
    dynasty_text = dynasty_text.replace("公元前", "").replace("公元", "")
    has_chinese_dynasty = bool(_CHINESE_DYNASTY_HINT_RE.search(dynasty_text))
    has_foreign_dynasty = bool(_FOREIGN_DYNASTY_HINT_RE.search(dynasty_text))
    if has_chinese_dynasty and not has_foreign_dynasty:
        return False
    if has_foreign_dynasty and not has_chinese_dynasty:
        return True
    place_texts = [str(value or "").strip() for value in (birthplace_modern, birthplace_raw) if str(value or "").strip()]
    for text in place_texts:
        if _FOREIGN_PLACE_HINT_RE.search(text):
            return True
    for text in place_texts:
        if _DOMESTIC_PLACE_HINT_RE.search(text):
            return False
    if has_chinese_dynasty:
        return False
    return bool(str(foreign_name or "").strip())


def _render_index_html(title: str, data_file: str, detail_file: str = "") -> str:
    safe_title = title.strip() or "故事地图"
    design_tokens = _design_tokens_style_tag()
    # Always render a fresh index.html instead of patching an existing template.
    # This prevents older inline JS/CSS (e.g. outdated AMap style) from lingering.
    static_site = bool(env_flag("MAP_STORY_STATIC_SITE", "GITHUB_PAGES_STATIC")) if env_flag else False
    api_base = _runtime_api_base_env()
    amap_key = str(os.getenv("AMAP_KEY", "")).strip()
    amap_sec = str(os.getenv("AMAP_SECURITY", "")).strip()
    amap_inline = ""
    if amap_key or amap_sec:
        parts = []
        if amap_key:
            parts.append(f"window.AMAP_KEY={json.dumps(amap_key, ensure_ascii=False)};")
        if amap_sec:
            parts.append(f"window.AMAP_SECURITY={json.dumps(amap_sec, ensure_ascii=False)};")
        amap_inline = "<script>" + "".join(parts) + "</script>"
    runtime_parts = [f"window.MAP_STORY_STATIC_SITE={'true' if static_site else 'false'};"]
    if api_base:
        runtime_parts.append(f"window.MAP_STORY_API_BASE={json.dumps(api_base, ensure_ascii=False)};")
    runtime_inline = "<script>" + "".join(runtime_parts) + "</script>"
    analytics_head = _analytics_head_html()
    shared_person_tooltip_js = person_tooltip_js()
    demo_banner = ""
    return rf"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <link rel="icon" type="image/png" sizes="32x32" href="./orange.png?v=20260617-tab" />
    <link rel="shortcut icon" href="./orange.png?v=20260617-tab" />
    <link rel="apple-touch-icon" href="./orange.png?v=20260617-tab" />
    {analytics_head}
    {amap_inline}
    {runtime_inline}
    {design_tokens}
    <script src="./vendor/tailwindcss.js"></script>
    <style>
      body {{
        color: var(--color-text);
      }}
      .glass {{
        background: rgba(255,255,255,0.84);
        border: 1px solid rgba(218,220,224,0.8);
        backdrop-filter: blur(16px);
      }}
      .card {{
        border-radius: var(--radius-xl);
        box-shadow: var(--shadow-md);
      }}
      .graph {{
        background:
          radial-gradient(1200px 720px at 10% 0%, rgba(26,115,232,0.2), transparent 56%),
          radial-gradient(760px 560px at 86% 12%, rgba(52,168,83,0.14), transparent 56%),
          radial-gradient(720px 520px at 40% 100%, rgba(251,188,4,0.14), transparent 58%),
          linear-gradient(140deg, #0f172a 0%, #14213d 56%, #10253f 100%);
      }}
      canvas {{ display:block; width:100%; }}
      .tooltip {{
        position: absolute;
        pointer-events: none;
        background: rgba(15,23,42,0.88);
        color: rgba(255,255,255,0.92);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        padding: 10px 12px;
        max-width: 280px;
        font-size: 12px;
        line-height: 1.45;
        box-shadow: 0 18px 34px rgba(0,0,0,0.26);
        z-index: 50;
      }}
      .home-work-chip {{
        display: inline-flex;
        align-items: center;
        max-width: 100%;
        padding: 3px 8px;
        border-radius: 999px;
        background: rgba(37, 99, 235, 0.08);
        border: 1px solid rgba(37, 99, 235, 0.18);
        color: #1d4ed8;
        font-size: 11px;
        line-height: 1.2;
        font-weight: 600;
        white-space: nowrap;
        cursor: help;
      }}
      .home-work-chip:hover {{
        background: rgba(37, 99, 235, 0.12);
        border-color: rgba(37, 99, 235, 0.26);
      }}
      .home-work-tooltip {{
        position: fixed;
        left: 0;
        top: 0;
        z-index: 180;
        min-width: 260px;
        max-width: min(420px, calc(100vw - 24px));
        max-height: min(280px, calc(100vh - 24px));
        overflow-y: auto;
        border-radius: 14px;
        border: 1px solid rgba(15, 23, 42, 0.08);
        background: rgba(255,255,255,0.98);
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.22);
        padding: 10px 12px;
        color: #334155;
        font-size: 12px;
        line-height: 1.55;
        pointer-events: none;
      }}
      input[type="range"] {{
        accent-color: rgba(255,255,255,0.85);
      }}
      button {{
        transition: transform 160ms ease, background-color 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
      }}
      button:active {{
        transform: translateY(1px);
      }}
      .range-rail {{
        height: 64px;
        border-radius: 14px;
        background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03));
        border: 1px solid rgba(255,255,255,0.16);
        touch-action: none;
        user-select: none;
        z-index: 2;
      }}
      .ticks {{
        background-image: none;
        pointer-events: none;
      }}
      .band {{
        background: rgba(255,255,255,0.035);
        border: 1px solid rgba(255,255,255,0.08);
        pointer-events: none;
      }}
      .range-mask {{
        background: rgba(2,6,23,0.48);
        border: 1px solid rgba(255,255,255,0.06);
        pointer-events: none;
      }}
      .range-sel {{
        background: linear-gradient(90deg, rgba(52,168,83,0.22), rgba(26,115,232,0.16));
        border: 1px solid rgba(255,255,255,0.26);
        box-shadow: 0 10px 24px rgba(0,0,0,0.28), inset 0 0 0 1px rgba(52,168,83,0.18);
        pointer-events: none;
      }}
      .handle {{
        width: 14px;
        height: 42px;
        border-radius: 10px;
        background: rgba(255,255,255,0.88);
        box-shadow: 0 8px 16px rgba(0,0,0,0.25);
        border: 1px solid rgba(15,23,42,0.25);
        cursor: ew-resize;
        touch-action: none;
      }}
      @keyframes twinkle {{
        0% {{ transform: scale(1); opacity: 0.82; }}
        50% {{ transform: scale(1.12); opacity: 1; }}
        100% {{ transform: scale(1); opacity: 0.86; }}
      }}
      .home-search-card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(248,249,250,0.92));
      }}
      .home-hero {{
        background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(232,240,254,0.74));
      }}
      .home-title-wrap {{
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 6px;
        margin-bottom: 14px;
        text-align: left;
      }}
      .home-title-mark {{
        display: inline-flex;
        align-items: center;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--color-primary);
      }}
      .home-title {{
        font-size: clamp(28px, 4vw, 40px);
        line-height: 1.06;
        font-weight: 900;
        letter-spacing: 0;
        color: var(--color-text);
        text-shadow: 0 1px 0 rgba(255,255,255,0.85);
      }}
      .home-title-link {{
        display: inline-flex;
        align-items: flex-end;
        gap: 0.18em;
        color: var(--color-text);
        text-decoration: none;
      }}
      .home-title-link:hover {{
        color: var(--color-text);
      }}
      .home-title-char {{
        display: inline-block;
      }}
      .home-title-sub {{
        font-size: 12px;
        line-height: 1.5;
        color: var(--color-text-secondary);
        max-width: 760px;
      }}
      .home-search-hint-line {{
        display: block;
        text-align: left;
      }}
      .home-search-hint-runtime {{
        display: block;
        text-align: left;
      }}
      .home-bili-highlight {{
        display: block;
        width: fit-content;
        max-width: 100%;
        padding: 2px 8px 2px 0;
        border-radius: 8px;
        background: #fef08a;
        font-size: 15px;
        line-height: 1.75;
        font-weight: 700;
        color: #713f12;
        text-align: left;
      }}
      .home-runtime-note {{
        display: block;
        color: #6b7280;
        font-size: 12px;
        line-height: 1.6;
        text-align: left;
      }}
      .home-bili-highlight a {{
        color: #1d4ed8;
        text-decoration: underline;
        font-weight: 800;
      }}
      .home-search-row {{
        display: flex;
        align-items: center;
        gap: 14px;
      }}
      .home-search-submit {{
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 54px;
        height: 54px;
        flex: 0 0 auto;
        border: 1px solid rgba(37, 99, 235, 0.22);
        border-radius: 999px;
        background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%);
        color: #ffffff;
        box-shadow:
          0 12px 22px rgba(37, 99, 235, 0.28),
          inset 0 -2px 0 rgba(15, 23, 42, 0.08);
        transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease, opacity 0.18s ease;
      }}
      .home-search-submit:hover {{
        transform: translateY(-1px);
        background: linear-gradient(180deg, #4f8ff8 0%, #2f6ded 100%);
        box-shadow:
          0 16px 26px rgba(37, 99, 235, 0.32),
          inset 0 -2px 0 rgba(255, 255, 255, 0.05);
      }}
      .home-search-submit:active {{
        transform: translateY(0);
      }}
      .home-search-submit:focus-visible {{
        outline: none;
        box-shadow:
          0 0 0 4px rgba(66, 133, 244, 0.22),
          0 18px 30px rgba(15, 23, 42, 0.26),
          inset 0 -2px 0 rgba(255, 255, 255, 0.05);
      }}
      .home-search-submit:disabled {{
        opacity: 0.72;
        cursor: not-allowed;
      }}
      .home-search-submit[data-loading="true"] {{
        background: linear-gradient(180deg, #4f8ff8 0%, #2f6ded 100%);
        animation: home-submit-pulse 1.05s ease-in-out infinite;
      }}
      .home-search-submit-icon {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        transition: transform 0.18s ease, opacity 0.18s ease;
      }}
      .home-search-submit[data-loading="true"] .home-search-submit-icon {{
        transform: scale(0.94);
        opacity: 0.78;
      }}
      .home-search-submit-icon svg {{
        display: block;
        width: 100%;
        height: 100%;
        stroke: currentColor;
        stroke-width: 2.5;
        stroke-linecap: round;
        stroke-linejoin: round;
        fill: none;
      }}
      .sr-only {{
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }}
      @keyframes home-submit-pulse {{
        0%, 100% {{
          transform: scale(1);
          box-shadow:
            0 14px 28px rgba(15, 23, 42, 0.22),
            inset 0 -2px 0 rgba(255, 255, 255, 0.04);
        }}
        50% {{
          transform: scale(0.97);
          box-shadow:
            0 10px 18px rgba(15, 23, 42, 0.18),
            inset 0 -2px 0 rgba(255, 255, 255, 0.03);
        }}
      }}
      .distribution-pane {{
        height: 500px;
      }}
      .distribution-frame {{
        height: 100%;
      }}
      #c {{
        display: block;
        width: 100%;
        height: 100%;
      }}
      .pixel-progress-shell {{
        position: fixed;
        right: 16px;
        bottom: 16px;
        z-index: 160;
        width: min(1180px, calc(100vw - 24px));
        max-height: min(920px, calc(100vh - 24px));
      }}
      .pixel-progress-shell.is-collapsed {{
        width: min(136px, calc(100vw - 24px));
        max-height: 40px;
      }}
      .pixel-progress-panel {{
        position: relative;
        display: flex;
        flex-direction: column;
        width: 100%;
        max-height: min(920px, calc(100vh - 24px));
        border-radius: 4px;
        overflow: hidden;
        border: 3px solid #1d4ed8;
        background:
          repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.04) 0,
            rgba(255,255,255,0.04) 12px,
            rgba(255,255,255,0.01) 12px,
            rgba(255,255,255,0.01) 24px
          ),
          linear-gradient(180deg, #203b96 0%, #152b72 34%, #0b173e 100%);
        box-shadow:
          0 0 0 2px #071632,
          0 0 0 5px rgba(8, 15, 37, 0.92),
          0 18px 0 rgba(5, 10, 24, 0.32),
          0 26px 34px rgba(9, 15, 37, 0.48);
        color: #edf2ff;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-panel {{
        border-width: 2px;
        border-radius: 999px;
        box-shadow:
          0 0 0 1px #071632,
          0 0 0 4px rgba(8, 15, 37, 0.92),
          0 6px 10px rgba(9, 15, 37, 0.22);
      }}
      .pixel-progress-shell {{
        cursor: default;
      }}
      .pixel-progress-panel::before {{
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        height: 5px;
        background: linear-gradient(90deg, #4285f4 0%, #ea4335 34%, #fbbc04 68%, #34a853 100%);
        z-index: 7;
      }}
      .pixel-progress-header {{
        position: sticky;
        top: 0;
        z-index: 6;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 8px 10px;
        background:
          repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.09) 0,
            rgba(255,255,255,0.09) 10px,
            rgba(255,255,255,0.03) 10px,
            rgba(255,255,255,0.03) 20px
          ),
          linear-gradient(180deg, rgba(55,102,214,0.46), rgba(20,47,128,0.28));
        border-bottom: 3px solid rgba(66, 133, 244, 0.42);
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-header {{
        gap: 0;
        padding: 4px 8px;
        border-bottom-width: 0;
        min-height: 28px;
      }}
      .pixel-progress-title {{
        flex: 1 1 auto;
        min-width: 0;
        display: grid;
        grid-template-columns: 16px minmax(0, 1fr) auto;
        align-items: center;
        column-gap: 10px;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-title {{
        grid-template-columns: 10px minmax(0, 1fr);
        column-gap: 6px;
      }}
      .pixel-progress-actions {{
        display: flex;
        align-items: center;
        gap: 6px;
        flex: 0 0 auto;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-actions {{
        display: flex;
      }}
      .pixel-progress-lamp {{
        width: 10px;
        height: 10px;
        flex: 0 0 auto;
        border-radius: 2px;
        background: #64748b;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.92), inset 0 -2px 0 rgba(0, 0, 0, 0.45);
      }}
      .pixel-progress-lamp.is-idle {{
        background: #4285f4;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.82), 0 0 8px rgba(66, 133, 244, 0.42);
      }}
      .pixel-progress-lamp.is-queued {{
        background: #fbbc04;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.82), 0 0 8px rgba(251, 188, 4, 0.42);
      }}
      .pixel-progress-lamp.is-running {{
        background: #34a853;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.82), 0 0 8px rgba(52, 168, 83, 0.42);
      }}
      .pixel-progress-lamp.is-failed {{
        background: #ea4335;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.82), 0 0 8px rgba(234, 67, 53, 0.42);
      }}
      .pixel-progress-lamp.is-completed {{
        background: #4285f4;
        box-shadow: 0 0 0 2px rgba(8, 11, 23, 0.82), 0 0 8px rgba(66, 133, 244, 0.42);
      }}
      .pixel-progress-meta {{
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }}
      .pixel-progress-caption {{
        font-size: 9px;
        line-height: 1.1;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: rgba(191, 219, 254, 0.76);
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-caption {{
        display: none;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-meta {{
        display: none;
      }}
      .pixel-progress-person {{
        margin-top: 0;
        font-size: 18px;
        font-weight: 700;
        color: #f8fbff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-shadow: 2px 2px 0 rgba(10, 16, 35, 0.45);
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-person {{
        font-size: 15px;
        line-height: 1.2;
      }}
      .pixel-progress-compact {{
        display: none;
        min-width: 0;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: #e5efff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.1;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-compact {{
        display: block;
      }}
      .pixel-progress-badge {{
        min-width: 54px;
        padding: 5px 8px 4px;
        border-radius: 4px;
        border: 2px solid rgba(255,255,255,0.18);
        background: rgba(15, 23, 42, 0.82);
        color: rgba(255,255,255,0.88);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-align: center;
        box-shadow: inset 0 -2px 0 rgba(0,0,0,0.26), 2px 2px 0 rgba(8, 11, 23, 0.28);
        justify-self: start;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-badge {{
        display: none;
      }}
      .pixel-progress-badge.is-idle {{
        background: rgba(66, 133, 244, 0.18);
        border-color: rgba(66, 133, 244, 0.48);
        color: #dbeafe;
      }}
      .pixel-progress-badge.is-queued {{
        background: rgba(251, 188, 4, 0.18);
        border-color: rgba(251, 188, 4, 0.46);
        color: #fef3c7;
      }}
      .pixel-progress-badge.is-running {{
        background: rgba(52, 168, 83, 0.18);
        border-color: rgba(52, 168, 83, 0.44);
        color: #dcfce7;
      }}
      .pixel-progress-badge.is-failed {{
        background: rgba(234, 67, 53, 0.18);
        border-color: rgba(234, 67, 53, 0.42);
        color: #fee2e2;
      }}
      .pixel-progress-badge.is-completed {{
        background: rgba(66, 133, 244, 0.2);
        border-color: rgba(52, 168, 83, 0.36);
        color: #dbeafe;
      }}
      .pixel-progress-icon-btn {{
        width: 28px;
        height: 28px;
        padding: 0;
        border: 2px solid rgba(255,255,255,0.2);
        border-radius: 4px;
        background: rgba(15, 23, 42, 0.56);
        color: #f8fbff;
        font-size: 15px;
        font-weight: 700;
        line-height: 1;
        box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.22), 2px 2px 0 rgba(8, 11, 23, 0.28);
        flex: 0 0 auto;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-icon-btn {{
        width: 22px;
        height: 22px;
        font-size: 12px;
        border-radius: 999px;
        margin-left: 2px;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-panel::before {{
        display: none;
      }}
      .pixel-progress-shell.is-collapsed .pixel-progress-lamp {{
        width: 8px;
        height: 8px;
        border-radius: 999px;
      }}
      .pixel-progress-body {{
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        min-height: 0;
        overflow: auto;
      }}
      .pixel-progress-body.is-star-office-only > :not(.pixel-progress-iframe-shell) {{
        display: none !important;
      }}
      .pixel-progress-iframe-shell {{
        position: relative;
        border: 2px solid rgba(66, 133, 244, 0.24);
        border-radius: 4px;
        overflow: hidden;
        background: rgba(8, 15, 36, 0.86);
        min-height: 560px;
        box-shadow: inset 0 0 0 2px rgba(255,255,255,0.03);
      }}
      .pixel-progress-iframe-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 8px 10px;
        border-bottom: 1px solid rgba(66, 133, 244, 0.16);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(191, 219, 254, 0.72);
      }}
      .pixel-progress-iframe {{
        display: block;
        width: 100%;
        height: 740px;
        border: 0;
        background: #1a1a2e;
      }}
      .pixel-progress-scene {{
        position: relative;
        min-height: 176px;
        border-radius: 4px;
        border: 2px solid rgba(66, 133, 244, 0.34);
        overflow: hidden;
        background:
          radial-gradient(circle at 18% 18%, rgba(66, 133, 244, 0.24), transparent 28%),
          radial-gradient(circle at 82% 24%, rgba(251, 188, 4, 0.16), transparent 22%),
          linear-gradient(180deg, rgba(66, 133, 244, 0.24), rgba(13, 24, 61, 0.98));
        transition: background 0.28s ease, border-color 0.28s ease, box-shadow 0.28s ease;
        box-shadow: inset 0 0 0 2px rgba(255,255,255,0.03), 4px 4px 0 rgba(8, 15, 36, 0.22);
      }}
      .pixel-progress-scene::before {{
        content: "";
        position: absolute;
        inset: 0;
        background: repeating-linear-gradient(
          90deg,
          rgba(255,255,255,0.045) 0,
          rgba(255,255,255,0.045) 14px,
          rgba(255,255,255,0.02) 14px,
          rgba(255,255,255,0.02) 28px
        );
        opacity: 0.58;
        pointer-events: none;
      }}
      .pixel-progress-scene[data-idle-scene="idle"] {{
        background:
          radial-gradient(circle at 18% 18%, rgba(255, 204, 128, 0.24), transparent 28%),
          radial-gradient(circle at 82% 24%, rgba(255, 146, 84, 0.14), transparent 22%),
          linear-gradient(180deg, rgba(72, 93, 150, 0.26), rgba(18, 28, 62, 0.98));
      }}
      .pixel-progress-scene[data-idle-scene="nap"] {{
        background:
          radial-gradient(circle at 18% 18%, rgba(132, 163, 255, 0.18), transparent 28%),
          radial-gradient(circle at 82% 24%, rgba(164, 147, 255, 0.1), transparent 22%),
          linear-gradient(180deg, rgba(34, 48, 102, 0.2), rgba(8, 15, 34, 0.99));
      }}
      .pixel-progress-scene[data-idle-scene="stroll"] {{
        background:
          radial-gradient(circle at 18% 18%, rgba(93, 214, 181, 0.18), transparent 28%),
          radial-gradient(circle at 82% 24%, rgba(84, 173, 255, 0.14), transparent 22%),
          linear-gradient(180deg, rgba(34, 79, 102, 0.22), rgba(11, 23, 46, 0.98));
      }}
      .pixel-progress-scene-floor {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 0;
        height: 26px;
        background: linear-gradient(180deg, rgba(77, 52, 40, 0.42), rgba(46, 31, 24, 0.68));
        border-top: 2px solid rgba(251, 188, 4, 0.22);
      }}
      .pixel-progress-scene-floor::before {{
        content: "";
        position: absolute;
        inset: 0;
        background: repeating-linear-gradient(
          90deg,
          rgba(255,255,255,0.05) 0,
          rgba(255,255,255,0.05) 18px,
          rgba(0,0,0,0.04) 18px,
          rgba(0,0,0,0.04) 36px
        );
      }}
      .pixel-progress-scene-title {{
        position: absolute;
        left: 12px;
        top: 10px;
        z-index: 3;
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(191, 219, 254, 0.84);
        text-shadow: 1px 1px 0 rgba(7, 11, 24, 0.4);
      }}
      .pixel-progress-status-lights {{
        position: absolute;
        right: 12px;
        top: 10px;
        z-index: 3;
        display: flex;
        gap: 6px;
      }}
      .pixel-progress-scene-light {{
        width: 10px;
        height: 10px;
        border-radius: 2px;
        background: #334155;
        box-shadow: 0 0 0 2px rgba(8,11,23,0.55), inset 0 -1px 0 rgba(0,0,0,0.4);
      }}
      .pixel-progress-scene-light.is-on {{
        animation: pixel-led-pulse 1s steps(2, end) infinite;
      }}
      .pixel-progress-scene-light.is-amber {{
        background: #fbbf24;
        box-shadow: 0 0 10px rgba(251, 191, 36, 0.45);
      }}
      .pixel-progress-scene-light.is-green {{
        background: #34a853;
        box-shadow: 0 0 10px rgba(52, 168, 83, 0.45);
      }}
      .pixel-progress-scene-light.is-cyan {{
        background: #4285f4;
        box-shadow: 0 0 10px rgba(66, 133, 244, 0.45);
      }}
      @keyframes pixel-led-pulse {{
        0%, 100% {{ filter: brightness(1); }}
        50% {{ filter: brightness(1.28); }}
      }}
      .pixel-progress-workbench {{
        position: absolute;
        left: 18px;
        right: 18px;
        bottom: 10px;
        z-index: 2;
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 14px;
      }}
      .pixel-ocelot-wrap {{
        position: relative;
        width: 138px;
        height: 112px;
        flex: 0 0 auto;
      }}
      .pixel-orange-pet-wrap {{
        position: relative;
        width: 138px;
        height: 112px;
        flex: 0 0 auto;
        transition: transform 0.28s ease, filter 0.28s ease;
      }}
      .pixel-orange-pet-img {{
        position: absolute;
        left: 10px;
        right: 10px;
        bottom: 6px;
        width: calc(100% - 20px);
        height: auto;
        max-height: 94px;
        object-fit: contain;
        filter: drop-shadow(0 10px 18px rgba(15, 23, 42, 0.22));
        z-index: 2;
      }}
      .pixel-orange-pet-fallback {{
        position: absolute;
        left: 24px;
        right: 24px;
        bottom: 12px;
        height: 74px;
        border-radius: 50% 50% 46% 46%;
        background: radial-gradient(circle at 34% 30%, #ffd19b 0 16%, #ff9f43 17% 44%, #f97316 45% 78%, #ea580c 79% 100%);
        box-shadow: inset -8px -10px 0 rgba(194, 65, 12, 0.22), 0 12px 24px rgba(15, 23, 42, 0.18);
        z-index: 1;
      }}
      .pixel-orange-pet-fallback::before {{
        content: "";
        position: absolute;
        left: 50%;
        top: -8px;
        width: 18px;
        height: 12px;
        border-radius: 12px 12px 2px 12px;
        background: linear-gradient(180deg, #4d7c0f 0%, #3f6212 100%);
        transform: translateX(-50%) rotate(-18deg);
        box-shadow: 0 0 0 2px rgba(255,255,255,0.14);
      }}
      .pixel-orange-pet-wrap[data-idle-scene="nap"] {{
        transform: translateY(4px) rotate(-3deg);
      }}
      .pixel-orange-pet-wrap[data-idle-scene="stroll"] {{
        transform: translateX(3px) rotate(2deg);
      }}
      .pixel-orange-pet-wrap[data-idle-scene="idle"] {{
        transform: translateY(-2px);
      }}
      .pixel-ocelot-cat {{
        position: absolute;
        left: 8px;
        right: 8px;
        bottom: 0;
        height: 108px;
        --ocelot-outline: #3f2c20;
        --ocelot-base: #b98a52;
        --ocelot-base-dark: #8a5f35;
        --ocelot-cream: #e9d7bc;
        --ocelot-cream-soft: #d7bf9f;
        --ocelot-spot: #4f3624;
        --ocelot-spot-soft: #6b4a33;
        --ocelot-eye: #90bf47;
        --ocelot-eye-shadow: #5f7d2c;
        --ocelot-nose: #8e6258;
        --ocelot-deskwood: #7b4d30;
        --ocelot-deskwood-dark: #53311e;
        --ocelot-monitor: #b8aa94;
        --ocelot-mug: #7a9891;
        transition: transform 0.28s ease, opacity 0.28s ease, filter 0.28s ease;
      }}
      .pixel-ocelot-ear {{
        position: absolute;
        top: 4px;
        width: 18px;
        height: 18px;
        background: var(--ocelot-base);
        border: 2px solid var(--ocelot-outline);
        transform: rotate(45deg);
        border-radius: 2px;
        z-index: 2;
      }}
      .pixel-ocelot-ear.left {{ left: 32px; }}
      .pixel-ocelot-ear.right {{ right: 32px; }}
      .pixel-ocelot-ear::after {{
        content: "";
        position: absolute;
        inset: 4px;
        background: var(--ocelot-cream);
      }}
      .pixel-ocelot-head {{
        position: absolute;
        left: 34px;
        top: 10px;
        width: 48px;
        height: 38px;
        border: 2px solid var(--ocelot-outline);
        background: linear-gradient(180deg, var(--ocelot-base) 0 56%, var(--ocelot-base-dark) 56% 100%);
        border-radius: 14px 14px 12px 12px;
        z-index: 3;
        transition: transform 0.28s ease;
      }}
      .pixel-ocelot-head::before,
      .pixel-ocelot-head::after {{
        content: "";
        position: absolute;
        top: 8px;
        width: 5px;
        height: 10px;
        background: var(--ocelot-spot);
        border-radius: 3px;
      }}
      .pixel-ocelot-head::before {{ left: 7px; }}
      .pixel-ocelot-head::after {{ right: 7px; }}
      .pixel-ocelot-face {{
        position: absolute;
        left: 11px;
        right: 11px;
        bottom: 4px;
        height: 16px;
        border-radius: 7px 7px 10px 10px;
        background: linear-gradient(180deg, var(--ocelot-cream) 0 72%, var(--ocelot-cream-soft) 72% 100%);
      }}
      .pixel-ocelot-face::before {{
        content: "";
        position: absolute;
        left: 50%;
        top: 3px;
        width: 6px;
        height: 5px;
        margin-left: -3px;
        background: var(--ocelot-nose);
        border-radius: 999px 999px 2px 2px;
        box-shadow:
          -7px 1px 0 -1px rgba(79, 54, 36, 0.42),
          7px 1px 0 -1px rgba(79, 54, 36, 0.42);
      }}
      .pixel-ocelot-face::after {{
        content: "";
        position: absolute;
        left: 50%;
        top: 9px;
        width: 14px;
        height: 5px;
        margin-left: -7px;
        border-bottom: 2px solid rgba(63, 44, 32, 0.72);
        border-radius: 0 0 14px 14px;
      }}
      .pixel-ocelot-eyes {{
        position: absolute;
        left: 14px;
        right: 14px;
        top: 15px;
        display: flex;
        justify-content: space-between;
      }}
      .pixel-ocelot-eyes span {{
        width: 6px;
        height: 7px;
        border-radius: 999px;
        background: linear-gradient(180deg, #bde16f 0 38%, var(--ocelot-eye) 38% 100%);
        box-shadow:
          inset 0 0 0 1px var(--ocelot-eye-shadow),
          inset 0 -2px 0 0 rgba(45, 34, 29, 0.48),
          0 0 0 1px rgba(28, 18, 12, 0.2);
      }}
      .pixel-ocelot-whiskers {{
        position: absolute;
        left: 3px;
        right: 3px;
        bottom: 8px;
        height: 8px;
        pointer-events: none;
      }}
      .pixel-ocelot-whiskers::before,
      .pixel-ocelot-whiskers::after {{
        content: "";
        position: absolute;
        top: 2px;
        width: 14px;
        height: 2px;
        border-top: 2px solid rgba(244, 235, 221, 0.95);
      }}
      .pixel-ocelot-whiskers::before {{
        left: 0;
        transform: rotate(8deg);
      }}
      .pixel-ocelot-whiskers::after {{
        right: 0;
        transform: rotate(-8deg);
      }}
      .pixel-ocelot-body {{
        position: absolute;
        left: 26px;
        bottom: 16px;
        width: 64px;
        height: 34px;
        border: 2px solid var(--ocelot-outline);
        background: linear-gradient(180deg, var(--ocelot-base) 0 52%, var(--ocelot-base-dark) 52% 100%);
        border-radius: 14px 14px 9px 9px;
        z-index: 1;
        transition: transform 0.28s ease, height 0.28s ease, border-radius 0.28s ease, opacity 0.28s ease;
      }}
      .pixel-ocelot-body::before {{
        content: "";
        position: absolute;
        left: 9px;
        top: 5px;
        width: 10px;
        height: 7px;
        background: rgba(79, 54, 36, 0.82);
        border-radius: 4px;
        box-shadow:
          12px 7px 0 0 rgba(79, 54, 36, 0.82),
          23px 1px 0 -1px rgba(107, 74, 51, 0.84),
          34px 8px 0 0 rgba(79, 54, 36, 0.82),
          41px 2px 0 -1px rgba(107, 74, 51, 0.8);
      }}
      .pixel-ocelot-body::after {{
        content: "";
        position: absolute;
        left: 18px;
        right: 12px;
        top: 14px;
        height: 10px;
        border-radius: 8px 10px 8px 12px;
        background: rgba(233, 215, 188, 0.58);
      }}
      .pixel-ocelot-tail {{
        position: absolute;
        right: 14px;
        bottom: 28px;
        width: 26px;
        height: 12px;
        border: 2px solid var(--ocelot-outline);
        border-radius: 999px;
        background: linear-gradient(180deg, var(--ocelot-base) 0 52%, var(--ocelot-base-dark) 52% 100%);
        transform-origin: left center;
        animation: pixel-tail-wave 1.8s steps(2, end) infinite;
        z-index: 0;
        transition: transform 0.28s ease, opacity 0.28s ease;
      }}
      .pixel-ocelot-tail::before,
      .pixel-ocelot-tail::after {{
        content: "";
        position: absolute;
        top: 1px;
        width: 3px;
        height: 6px;
        background: rgba(79, 54, 36, 0.86);
      }}
      .pixel-ocelot-tail::before {{ left: 6px; }}
      .pixel-ocelot-tail::after {{ left: 15px; }}
      @keyframes pixel-tail-wave {{
        0%, 100% {{ transform: rotate(0deg); }}
        50% {{ transform: rotate(-9deg); }}
      }}
      .pixel-ocelot-desk {{
        position: absolute;
        left: 4px;
        right: 4px;
        bottom: 0;
        height: 18px;
        border: 2px solid #3f2618;
        background: linear-gradient(180deg, var(--ocelot-deskwood), var(--ocelot-deskwood-dark));
        box-shadow: inset 0 -2px 0 rgba(0,0,0,0.18);
      }}
      .pixel-ocelot-paw {{
        position: absolute;
        bottom: 18px;
        width: 16px;
        height: 10px;
        border: 2px solid var(--ocelot-outline);
        background: linear-gradient(180deg, var(--ocelot-base), var(--ocelot-base-dark));
        border-radius: 4px;
        z-index: 5;
        transition: transform 0.28s ease, left 0.28s ease, bottom 0.28s ease, opacity 0.28s ease;
      }}
      .pixel-ocelot-paw.left {{
        left: 44px;
        animation: pixel-paw-type-left 0.66s steps(2, end) infinite;
      }}
      .pixel-ocelot-paw.right {{
        left: 62px;
        animation: pixel-paw-type-right 0.66s steps(2, end) infinite;
      }}
      .pixel-ocelot-spot {{
        position: absolute;
        background: rgba(79, 54, 36, 0.82);
        border-radius: 3px;
      }}
      .pixel-ocelot-spot.head-left {{
        left: 41px;
        top: 16px;
        width: 5px;
        height: 8px;
        box-shadow: 8px -3px 0 -1px rgba(107, 74, 51, 0.82);
      }}
      .pixel-ocelot-spot.head-right {{
        right: 41px;
        top: 16px;
        width: 5px;
        height: 8px;
        box-shadow: -8px -3px 0 -1px rgba(107, 74, 51, 0.82);
      }}
      .pixel-ocelot-spot.body-center {{
        left: 47px;
        top: 61px;
        width: 10px;
        height: 7px;
        background: rgba(79, 54, 36, 0.82);
        box-shadow:
          -14px 5px 0 0 rgba(107, 74, 51, 0.82),
          14px 2px 0 0 rgba(107, 74, 51, 0.8);
      }}
      .pixel-ocelot-lamp {{
        position: absolute;
        left: 10px;
        bottom: 18px;
        width: 18px;
        height: 38px;
        z-index: 3;
      }}
      .pixel-ocelot-lamp::before {{
        content: "";
        position: absolute;
        left: 5px;
        bottom: 0;
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: #af7c4c;
        border: 2px solid var(--ocelot-outline);
      }}
      .pixel-ocelot-lamp::after {{
        content: "";
        position: absolute;
        left: 8px;
        top: 4px;
        width: 3px;
        height: 24px;
        background: #af7c4c;
        border-radius: 999px;
        box-shadow: 5px 4px 0 0 #af7c4c, 5px 18px 0 0 rgba(255, 207, 110, 0.88);
        transition: box-shadow 0.28s ease, opacity 0.28s ease;
      }}
      .pixel-ocelot-mug {{
        position: absolute;
        right: 16px;
        bottom: 18px;
        width: 10px;
        height: 12px;
        border: 2px solid #5f7f78;
        border-radius: 2px 2px 4px 4px;
        background: var(--ocelot-mug);
        z-index: 3;
        transition: transform 0.28s ease, opacity 0.28s ease;
      }}
      .pixel-ocelot-mug::after {{
        content: "";
        position: absolute;
        right: -5px;
        top: 2px;
        width: 4px;
        height: 5px;
        border: 2px solid #5f7f78;
        border-left: none;
        border-radius: 0 4px 4px 0;
      }}
      .pixel-ocelot-treat {{
        position: absolute;
        left: 92px;
        top: 30px;
        width: 18px;
        height: 6px;
        border: 2px solid #8d5d33;
        border-radius: 999px;
        background: linear-gradient(90deg, #f4d9bc 0 56%, #e6806d 56% 100%);
        display: none;
        z-index: 6;
      }}
      .pixel-ocelot-dream {{
        position: absolute;
        right: 8px;
        top: 2px;
        display: none;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: rgba(255, 248, 238, 0.88);
        text-shadow: 0 0 8px rgba(255,255,255,0.12);
        z-index: 6;
      }}
      .pixel-ocelot-footprints {{
        position: absolute;
        left: 20px;
        bottom: 16px;
        width: 22px;
        height: 8px;
        display: none;
        z-index: 3;
      }}
      .pixel-ocelot-footprints::before,
      .pixel-ocelot-footprints::after {{
        content: "";
        position: absolute;
        width: 7px;
        height: 5px;
        border-radius: 999px;
        background: rgba(255, 244, 231, 0.7);
      }}
      .pixel-ocelot-footprints::before {{
        left: 0;
        top: 3px;
      }}
      .pixel-ocelot-footprints::after {{
        right: 0;
        top: 0;
      }}
      .pixel-ocelot-wrap[data-idle-scene="snack"] .pixel-ocelot-treat {{
        display: block;
      }}
      .pixel-ocelot-wrap[data-idle-scene="snack"] .pixel-ocelot-head {{
        transform: rotate(-6deg) translateY(-1px);
      }}
      .pixel-ocelot-wrap[data-idle-scene="snack"] .pixel-ocelot-paw.right {{
        transform: translateY(-3px) translateX(3px);
      }}
      .pixel-ocelot-wrap[data-idle-scene="snack"] .pixel-ocelot-lamp::after {{
        box-shadow: 5px 4px 0 0 #af7c4c, 5px 18px 0 0 rgba(255, 220, 142, 0.95);
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-dream {{
        display: block;
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-head {{
        transform: translateY(6px);
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-body {{
        transform: translateY(6px);
        height: 28px;
        border-radius: 14px 14px 12px 12px;
        opacity: 0.95;
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-eyes span {{
        height: 2px;
        margin-top: 2px;
        border-radius: 2px;
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-paw {{
        opacity: 0.42;
        bottom: 14px;
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-tail {{
        animation-duration: 2.8s;
        opacity: 0.72;
      }}
      .pixel-ocelot-wrap[data-idle-scene="nap"] .pixel-ocelot-lamp::after {{
        opacity: 0.6;
        box-shadow: 5px 4px 0 0 #af7c4c, 5px 18px 0 0 rgba(155, 171, 255, 0.28);
      }}
      .pixel-ocelot-wrap[data-idle-scene="stroll"] .pixel-ocelot-cat {{
        transform: translateX(14px) translateY(-4px);
      }}
      .pixel-ocelot-wrap[data-idle-scene="stroll"] .pixel-ocelot-footprints {{
        display: block;
      }}
      .pixel-ocelot-wrap[data-idle-scene="stroll"] .pixel-ocelot-paw.left {{
        left: 52px;
        bottom: 16px;
      }}
      .pixel-ocelot-wrap[data-idle-scene="stroll"] .pixel-ocelot-paw.right {{
        left: 70px;
        bottom: 15px;
      }}
      .pixel-ocelot-wrap[data-idle-scene="stroll"] .pixel-ocelot-lamp::after {{
        box-shadow: 5px 4px 0 0 #af7c4c, 5px 18px 0 0 rgba(132, 183, 255, 0.86);
      }}
      @keyframes pixel-paw-type-left {{
        0%, 100% {{ transform: translateY(0); }}
        50% {{ transform: translateY(3px); }}
      }}
      @keyframes pixel-paw-type-right {{
        0%, 100% {{ transform: translateY(3px); }}
        50% {{ transform: translateY(0); }}
      }}
      .pixel-progress-bubble {{
        position: relative;
        flex: 1 1 auto;
        min-height: 104px;
        padding: 14px 15px 15px;
        border-radius: 4px;
        border: 2px solid rgba(66, 133, 244, 0.28);
        background:
          linear-gradient(180deg, rgba(17, 31, 84, 0.92), rgba(8, 17, 50, 0.88));
        box-shadow: inset 0 0 0 2px rgba(255,255,255,0.03), 4px 4px 0 rgba(8, 15, 36, 0.2);
      }}
      .pixel-progress-bubble::after {{
        content: "";
        position: absolute;
        left: -8px;
        bottom: 24px;
        width: 12px;
        height: 12px;
        transform: rotate(45deg);
        background: rgba(9, 20, 58, 0.92);
        border-left: 2px solid rgba(66, 133, 244, 0.28);
        border-bottom: 2px solid rgba(66, 133, 244, 0.28);
      }}
      .pixel-progress-bubble-title {{
        font-size: 10px;
        line-height: 1.1;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(191, 219, 254, 0.82);
      }}
      .pixel-progress-speech {{
        margin-top: 10px;
        min-height: 52px;
        font-size: 12px;
        line-height: 1.55;
        color: #f8fbff;
        white-space: pre-wrap;
        word-break: break-word;
      }}
      .pixel-progress-speech::after {{
        content: "";
        display: inline-block;
        width: 8px;
        height: 14px;
        margin-left: 4px;
        vertical-align: -2px;
        background: rgba(191, 219, 254, 0.92);
        animation: pixel-caret 1s steps(2, end) infinite;
      }}
      @keyframes pixel-caret {{
        0%, 49% {{ opacity: 1; }}
        50%, 100% {{ opacity: 0; }}
      }}
      .pixel-progress-stage-wrap {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }}
      .pixel-progress-group {{
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}
      .pixel-progress-group-label {{
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(191, 219, 254, 0.54);
      }}
      .pixel-progress-stage {{
        font-size: 13px;
        font-weight: 700;
        color: #fbbc04;
        text-shadow: 0 0 12px rgba(251, 188, 4, 0.18);
      }}
      .pixel-progress-status {{
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(226, 232, 240, 0.62);
      }}
      .pixel-progress-steps {{
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 6px;
      }}
      .pixel-progress-step {{
        min-height: 36px;
        padding: 6px 4px;
        border-radius: 4px;
        border: 2px solid rgba(148, 163, 184, 0.18);
        background: rgba(15, 23, 42, 0.52);
        backdrop-filter: blur(10px);
        text-align: center;
        font-size: 10px;
        line-height: 1.2;
        color: rgba(191, 219, 254, 0.58);
        box-shadow: inset 0 -2px 0 rgba(0,0,0,0.22);
      }}
      .pixel-progress-step.is-done {{
        border-color: rgba(52, 168, 83, 0.24);
        background: rgba(52, 168, 83, 0.14);
        color: rgba(220, 252, 231, 0.9);
      }}
      .pixel-progress-step.is-active {{
        border-color: rgba(66, 133, 244, 0.42);
        background: linear-gradient(180deg, rgba(66, 133, 244, 0.28), rgba(23, 78, 166, 0.22));
        color: #eff6ff;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04), 0 0 18px rgba(66, 133, 244, 0.12);
      }}
      .pixel-progress-card {{
        border: 2px solid rgba(66, 133, 244, 0.18);
        border-radius: 4px;
        background:
          linear-gradient(180deg, rgba(13, 28, 72, 0.9), rgba(8, 17, 50, 0.82));
        padding: 12px;
        box-shadow: inset 0 0 0 2px rgba(255,255,255,0.03);
      }}
      .pixel-progress-card.is-clickable {{
        cursor: pointer;
      }}
      .pixel-progress-card-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }}
      .pixel-progress-card-title {{
        font-size: 10px;
        line-height: 1.1;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(148, 163, 184, 0.74);
      }}
      .pixel-progress-card-hint {{
        font-size: 10px;
        color: rgba(191, 219, 254, 0.62);
      }}
      .pixel-progress-detail {{
        font-size: 12px;
        line-height: 1.55;
        color: #e2e8f0;
        word-break: break-word;
      }}
      .pixel-progress-opsbar {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 6px;
      }}
      .pixel-progress-opschip {{
        padding: 7px 8px;
        border-radius: 6px;
        border: 1px solid rgba(148, 163, 184, 0.12);
        background: rgba(15, 23, 42, 0.46);
        box-shadow: inset 0 -2px 0 rgba(0,0,0,0.12);
      }}
      .pixel-progress-opschip-label {{
        font-size: 9px;
        line-height: 1.1;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(148, 163, 184, 0.74);
      }}
      .pixel-progress-opschip-value {{
        margin-top: 4px;
        font-size: 11px;
        font-weight: 700;
        color: #e2e8f0;
        line-height: 1.35;
        word-break: break-word;
      }}
      .pixel-progress-opschip.is-success {{
        border-color: rgba(52, 168, 83, 0.22);
        background: rgba(52, 168, 83, 0.12);
      }}
      .pixel-progress-opschip.is-warning {{
        border-color: rgba(251, 188, 4, 0.24);
        background: rgba(251, 188, 4, 0.12);
      }}
      .pixel-progress-opschip.is-error {{
        border-color: rgba(234, 67, 53, 0.24);
        background: rgba(234, 67, 53, 0.1);
      }}
      .pixel-progress-opschip.is-muted {{
        border-color: rgba(148, 163, 184, 0.12);
        background: rgba(15, 23, 42, 0.46);
      }}
      .pixel-progress-agents {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 6px;
      }}
      .pixel-progress-agent {{
        padding: 8px 6px;
        border-radius: 4px;
        border: 2px solid rgba(148, 163, 184, 0.14);
        background: rgba(15, 23, 42, 0.46);
        color: rgba(191, 219, 254, 0.56);
        text-align: center;
        box-shadow: inset 0 -2px 0 rgba(0,0,0,0.18);
      }}
      .pixel-progress-agent.is-active {{
        border-color: rgba(251, 188, 4, 0.34);
        background: linear-gradient(180deg, rgba(251, 188, 4, 0.18), rgba(197, 138, 0, 0.12));
        color: #fef3c7;
        box-shadow: 0 0 14px rgba(251, 188, 4, 0.12);
      }}
      .pixel-progress-agent.is-done {{
        border-color: rgba(52, 168, 83, 0.2);
        background: rgba(52, 168, 83, 0.12);
        color: #d1fae5;
      }}
      .pixel-progress-agent-name {{
        font-size: 10px;
        font-weight: 700;
      }}
      .pixel-progress-agent-role {{
        margin-top: 3px;
        font-size: 9px;
        line-height: 1.25;
        opacity: 0.88;
      }}
      .pixel-progress-agent-status {{
        margin-top: 4px;
        font-size: 8px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        opacity: 0.72;
      }}
      .pixel-progress-detail.is-collapsed {{
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }}
      .pixel-progress-log {{
        display: flex;
        flex-direction: column;
        gap: 6px;
        max-height: 180px;
        overflow: auto;
        padding-right: 2px;
      }}
      .pixel-progress-log-item {{
        padding: 7px 8px;
        border-radius: 6px;
        background: rgba(30, 41, 59, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.12);
      }}
      .pixel-progress-log-label {{
        font-size: 11px;
        font-weight: 700;
        color: #f8fafc;
      }}
      .pixel-progress-log-detail {{
        margin-top: 2px;
        font-size: 11px;
        line-height: 1.45;
        color: rgba(226, 232, 240, 0.7);
        word-break: break-word;
      }}
      .pixel-progress-footer {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding-top: 2px;
        border-top: 1px solid rgba(66, 133, 244, 0.16);
        font-size: 10px;
        color: rgba(191, 219, 254, 0.72);
      }}
      .pixel-progress-mini {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        color: #e2e8f0;
      }}
      .pixel-progress-mini-bar {{
        width: 76px;
        height: 8px;
        border-radius: 999px;
        background: rgba(30, 41, 59, 0.96);
        border: 1px solid rgba(148, 163, 184, 0.18);
        overflow: hidden;
      }}
      .pixel-progress-mini-fill {{
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #4285f4 0%, #ea4335 34%, #fbbc04 68%, #34a853 100%);
      }}
      @media (max-width: 640px) {{
        .home-search-row {{
          gap: 10px;
        }}
        .home-search-submit {{
          width: 48px;
          height: 48px;
        }}
        .home-search-submit-icon {{
          width: 21px;
          height: 21px;
        }}
        .pixel-progress-shell {{
          right: 12px;
          bottom: 12px;
          width: calc(100vw - 24px);
          max-height: min(760px, calc(100vh - 20px));
        }}
        .pixel-progress-workbench {{
          gap: 10px;
        }}
        .pixel-ocelot-wrap,
        .pixel-orange-pet-wrap {{
          width: 110px;
          transform: scale(0.9);
          transform-origin: left bottom;
        }}
        .pixel-progress-agents {{
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }}
        .pixel-progress-opsbar {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
        .pixel-progress-iframe {{
          height: 620px;
        }}
      }}
    </style>
  </head>
  <body class="min-h-screen">
    <div class="max-w-[1310px] mx-auto px-4 py-6 space-y-4">
      {demo_banner}
      <div class="glass card theme-card home-search-card px-6 py-5 relative z-30 overflow-visible">
        <div class="home-title-wrap">
          <div class="home-title-mark">STORY MAP</div>
          <a class="home-title home-title-link" href="https://www.bilibili.com/video/BV1u3LX66Eh7/" target="_blank" rel="noreferrer">
            <span class="home-title-char">故</span>
            <span class="home-title-char">事</span>
            <span class="home-title-char">地</span>
            <span class="home-title-char">图</span>
          </a>
        </div>
        <div class="relative">
          <div class="home-search-row">
            <input id="q" class="theme-input flex-1 px-4 py-2.5 rounded-xl" placeholder="例如：苏轼 / 李白 / 杜甫" />
            <button id="go" class="home-search-submit" type="button" aria-label="开始分析" title="开始分析" data-loading="false">
              <span class="home-search-submit-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
                  <path d="M12 18V6"></path>
                  <path d="M6.5 11.5L12 6l5.5 5.5"></path>
                </svg>
              </span>
              <span class="sr-only home-search-submit-label">开始分析</span>
            </button>
          </div>
          <div id="searchValidation" class="hidden mt-2 text-xs text-amber-200"></div>
          <div id="searchHint" class="home-title-sub mt-2"><span class="home-search-hint-line"><strong>1. 内置人教版教材500+历史人物，可以直接访问</strong></span><span class="home-bili-highlight">2. 欢迎B站用户投币 投币 三连：<a href="https://www.bilibili.com/video/BV1u3LX66Eh7/" target="_blank" rel="noopener noreferrer">「我把2000年中国名人做成了动态地图，还能和李白聊天」</a></span></div>
          <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span class="theme-subtitle">快速体验：</span>
            <a class="theme-button-secondary px-3 py-1.5 rounded-xl" href="./李白.html">李白</a>
            <a class="theme-button-secondary px-3 py-1.5 rounded-xl" href="./苏轼.html">苏轼</a>
            <a class="theme-button-secondary px-3 py-1.5 rounded-xl" href="./关羽.html">关羽</a>
          </div>
          <div id="searchSuggest" class="theme-card hidden absolute left-0 right-0 top-full mt-2 z-[120] rounded-2xl bg-white/95 backdrop-blur shadow-2xl overflow-hidden"></div>
        </div>
        <div id="genStatus" class="hidden mt-2 text-xs theme-subtitle"></div>
      </div>
      <div id="pixelGenPanel" class="pixel-progress-shell is-collapsed" role="status" aria-live="polite" aria-label="系统状态：待命中" title="系统状态：只读展示，不能手动暂停或恢复">
        <div class="pixel-progress-panel">
          <div class="pixel-progress-header">
            <div class="pixel-progress-title">
              <div id="pixelGenLamp" class="pixel-progress-lamp"></div>
              <div id="pixelGenCompactText" class="pixel-progress-compact">待命中</div>
              <div class="pixel-progress-meta">
                <div class="pixel-progress-caption">Story Console</div>
                <div id="pixelGenPerson" class="pixel-progress-person">橙子Agent</div>
              </div>
              <div id="pixelGenStatusBadge" class="pixel-progress-badge is-idle">待命</div>
            </div>
            <div class="pixel-progress-actions">
              <button id="pixelGenToggle" class="pixel-progress-icon-btn" type="button" aria-expanded="false" aria-label="查看 Orange Office 详情（状态只读）" title="查看 Orange Office 详情（状态只读，不能手动暂停或恢复）">↗</button>
            </div>
          </div>
          <div id="pixelGenBody" class="pixel-progress-body is-star-office-only" style="display:none">
            <div class="pixel-progress-iframe-shell">
              <div class="pixel-progress-iframe-head">
                <span>Star Office</span>
              </div>
              <iframe
                id="pixelGenOfficeFrame"
                class="pixel-progress-iframe"
                src="./orange-office.html"
                loading="lazy"
                referrerpolicy="no-referrer"
                title="Star Office UI 工作台"
              ></iframe>
            </div>
            <div id="pixelGenScene" class="pixel-progress-scene">
              <div id="pixelGenSceneTitle" class="pixel-progress-scene-title">工位</div>
              <div id="pixelGenSceneLights" class="pixel-progress-status-lights">
                <div class="pixel-progress-scene-light"></div>
                <div class="pixel-progress-scene-light"></div>
                <div class="pixel-progress-scene-light"></div>
              </div>
              <div class="pixel-progress-workbench">
                <div id="pixelOcelotWrap" class="pixel-orange-pet-wrap" data-idle-scene="idle">
                  <img class="pixel-orange-pet-img" src="./{HOMEPAGE_PET_ASSET_OUTPUT_NAME}" alt="橙子工位形象" loading="eager" decoding="async" onerror="this.style.display='none';" />
                  <div class="pixel-orange-pet-fallback" aria-hidden="true"></div>
                </div>
                <div class="pixel-progress-bubble">
                  <div class="pixel-progress-bubble-title">状态</div>
                  <div id="pixelGenSpeech" class="pixel-progress-speech">空闲中</div>
                </div>
              </div>
              <div class="pixel-progress-scene-floor"></div>
            </div>
            <div class="pixel-progress-stage-wrap">
              <div id="pixelGenStage" class="pixel-progress-stage">空闲中</div>
              <div id="pixelGenStatusText" class="pixel-progress-status">待命</div>
            </div>
            <div id="pixelGenOpsBar" class="pixel-progress-opsbar">
              <div id="pixelGenOpsServe" class="pixel-progress-opschip is-muted">
                <div class="pixel-progress-opschip-label">浏览态</div>
                <div class="pixel-progress-opschip-value">检查中</div>
              </div>
              <div id="pixelGenOpsGenerate" class="pixel-progress-opschip is-muted">
                <div class="pixel-progress-opschip-label">生成态</div>
                <div class="pixel-progress-opschip-value">检查中</div>
              </div>
              <div id="pixelGenOpsQueue" class="pixel-progress-opschip is-muted">
                <div class="pixel-progress-opschip-label">队列</div>
                <div class="pixel-progress-opschip-value">等待采样</div>
              </div>
              <div id="pixelGenOpsDeps" class="pixel-progress-opschip is-muted">
                <div class="pixel-progress-opschip-label">依赖</div>
                <div class="pixel-progress-opschip-value">等待采样</div>
              </div>
            </div>
            <div class="pixel-progress-group">
              <div class="pixel-progress-group-label">流程阶段</div>
              <div id="pixelGenSteps" class="pixel-progress-steps"></div>
            </div>
            <div class="pixel-progress-group">
              <div class="pixel-progress-group-label">执行模块</div>
              <div id="pixelGenAgents" class="pixel-progress-agents"></div>
            </div>
            <div id="pixelGenDetailCard" class="pixel-progress-card is-clickable">
              <div class="pixel-progress-card-head">
                <div class="pixel-progress-card-title">摘要</div>
                <div id="pixelGenDetailHint" class="pixel-progress-card-hint">点击展开</div>
              </div>
              <div id="pixelGenDetail" class="pixel-progress-detail"></div>
            </div>
            <div class="pixel-progress-card">
              <div class="pixel-progress-card-head">
                <div class="pixel-progress-card-title">最近日志</div>
              </div>
              <div id="pixelGenLog" class="pixel-progress-log"></div>
            </div>
            <div class="pixel-progress-footer">
              <div id="pixelGenFooterText">空闲中</div>
              <div class="pixel-progress-mini">
                <span id="pixelGenPercent">0%</span>
                <div class="pixel-progress-mini-bar">
                  <div id="pixelGenFill" class="pixel-progress-mini-fill"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card graph theme-graph-panel overflow-hidden relative z-10">
        <div class="px-5 py-4 text-sm font-bold text-white/90 flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div>人类群星闪耀时</div>
            <div class="flex items-center gap-1 text-[11px] font-normal">
              <button id="tabGraph" class="px-3 py-1 rounded-lg bg-white/15 border border-white/20 text-white/90">时间分布</button>
              <button id="tabMap" class="px-3 py-1 rounded-lg bg-white/5 border border-white/10 text-white/70 hover:bg-white/10">空间分布</button>
            </div>
          </div>
          <div class="text-[11px] font-normal text-white/60 flex items-center gap-2 flex-wrap justify-end">
            窗口内：<span id="activeCount">-</span>
          </div>
        </div>
        <div class="px-5 pb-2 -mt-2 text-[11px] text-white/60">拖动时间窗筛选人物；悬停查看简介；点击节点进入人物页</div>
        <div class="px-5 pb-2 -mt-1 text-[11px] text-white/55 flex items-center justify-between gap-3 flex-wrap">
          <div class="flex items-center gap-x-4 gap-y-1 flex-wrap">
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#34a853"></span><span>先秦/公元前</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#ea4335"></span><span>秦汉</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#4285f4"></span><span>魏晋南北朝</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#fbbc04"></span><span>隋</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#1a73e8"></span><span>唐</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#7e57c2"></span><span>宋元</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#0f9d58"></span><span>明清</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#ff7043"></span><span>近代</span></div>
            <div class="flex items-center gap-2"><span class="inline-block w-2.5 h-2.5 rounded-full" style="background:#c0ca33"></span><span>现代</span></div>
          </div>
          <div id="mapToolbar" class="hidden items-center gap-2 text-[11px] text-white/70 relative">
            <div class="relative">
              <input id="mapSearchInput" type="text" placeholder="按省份查找"
                class="pl-2 pr-6 py-1 rounded-lg bg-white/10 border border-white/15 text-white/85 placeholder-white/40 outline-none focus:ring-2 focus:ring-white/20 w-[160px]"
                autocomplete="off" />
              <button id="mapSearchClear" class="hidden absolute right-1 top-1/2 -translate-y-1/2 w-4 h-4 leading-[14px] text-center rounded-full bg-white/15 text-white/70 hover:bg-white/25" type="button" aria-label="清除">×</button>
              <div id="mapSearchSuggest" class="hidden absolute right-0 top-full mt-1 z-30 w-[240px] max-h-[240px] overflow-y-auto rounded-xl bg-[rgba(8,15,36,0.92)] border border-white/15 shadow-2xl backdrop-blur-md"></div>
            </div>
            <button id="resetMap" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 text-white/70 hover:bg-white/15">重置视图</button>
          </div>
        </div>

        <div class="relative px-6 pb-4 overflow-hidden">
          <div id="tabTrack" class="relative">
            <div id="graphPane" class="relative distribution-pane">
              <div class="rounded-xl overflow-hidden border border-white/10 distribution-frame">
                <canvas id="c" width="900" height="500"></canvas>
              </div>
              <div class="absolute left-5 top-5 z-10 flex flex-col gap-2 text-[11px] text-white/80">
              </div>
              <div id="tip" class="tooltip hidden"></div>
            </div>
            <div id="mapPane" class="relative hidden distribution-pane">
              <div id="chinaMap" class="rounded-xl overflow-hidden border border-white/10 distribution-frame"></div>
              <div id="mapTip" class="tooltip hidden"></div>
              <div id="provinceCurvePanel" class="hidden absolute right-4 bottom-4 z-10 w-[280px] max-w-[calc(100%-32px)] px-3 py-2 rounded-xl bg-[rgba(8,15,36,0.72)] border border-white/10 backdrop-blur-md shadow-[0_18px_50px_rgba(15,23,42,0.28)]">
                <div class="flex items-center justify-between text-[11px]">
                  <div class="text-white/80 font-bold">各省份名人数量 Top5</div>
                </div>
                <div class="mt-1 text-[10px] text-white/50">按出生地汇总</div>
                <div id="provinceBars" class="mt-2 max-h-[136px] overflow-y-auto pr-1" style="scrollbar-width: thin;"></div>
              </div>
            </div>
          </div>
        </div>

        <div class="px-6 pb-6">
          <div class="range-rail relative px-3 py-3">
            <div class="absolute top-2 h-[12px] rounded-lg band flex items-start justify-between px-2 pt-[1px] text-[10px] text-white/55" id="bands" style="left:18px;right:18px;"></div>
            <div id="ticks" class="absolute top-1/2 -translate-y-1/2 h-[34px] rounded-xl bg-white/5 border border-white/10 ticks" style="left:18px;right:18px;"></div>
            <div id="maskL" class="absolute top-1/2 -translate-y-1/2 h-[34px] rounded-xl range-mask"></div>
            <div id="maskR" class="absolute top-1/2 -translate-y-1/2 h-[34px] rounded-xl range-mask"></div>
            <div id="sel" class="absolute top-1/2 -translate-y-1/2 h-[34px] rounded-xl range-sel"></div>
            <div id="lifeBar" class="absolute top-1/2 -translate-y-1/2 h-[6px] rounded-full bg-white/15 border border-white/20 hidden"></div>
            <div id="mBirth" class="absolute top-1/2 -translate-y-1/2 h-[34px] w-[2px] bg-emerald-300/70 hidden"></div>
            <div id="mDeath" class="absolute top-1/2 -translate-y-1/2 h-[34px] w-[2px] bg-rose-300/70 hidden"></div>
            <div id="h1" class="handle absolute top-1/2 -translate-y-1/2"></div>
            <div id="h2" class="handle absolute top-1/2 -translate-y-1/2"></div>
            <div class="absolute left-5 bottom-2 text-[10px] text-white/55" id="minLabel"></div>
            <div class="absolute right-5 bottom-2 text-[10px] text-white/55 text-right" id="maxLabel"></div>
            <div class="absolute left-1/2 -translate-x-1/2 bottom-2 text-[10px] text-white/55" id="midLabel"></div>
          </div>
          <div class="flex items-center justify-between mt-2 text-[11px] text-white/55">
            <div class="flex items-center gap-2">
              <span>起：</span>
              <input id="startYearInput" class="w-24 px-2 py-1 rounded-lg bg-white/10 border border-white/15 text-white/80 outline-none focus:ring-2 focus:ring-white/10" type="number" min="{MIN_YEAR}" max="{MAX_YEAR}" step="1" inputmode="numeric" />
            </div>
            <div>窗口跨度：约 <span id="spanYear">-</span> 年</div>
            <div class="flex items-center gap-2">
              <span>止：</span>
              <input id="endYearInput" class="w-24 px-2 py-1 rounded-lg bg-white/10 border border-white/15 text-white/80 outline-none focus:ring-2 focus:ring-white/10" type="number" min="{MIN_YEAR}" max="{MAX_YEAR}" step="1" inputmode="numeric" />
            </div>
          </div>
          <div id="timeRangeHint" class="hidden mt-2 text-[11px] text-amber-200"></div>
          <div class="flex flex-wrap items-center justify-center gap-1.5 mt-3 text-[11px] text-white/60 max-w-[1020px] mx-auto" id="presetBar">
            <button data-preset="all" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">全部</button>
            <button data-preset="preqin" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">春秋战国</button>
            <button data-preset="qin" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">秦</button>
            <button data-preset="han" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">汉</button>
            <button data-preset="weijin" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">魏晋南北</button>
            <button data-preset="sui" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">隋</button>
            <button data-preset="tang" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">唐</button>
            <button data-preset="song" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">宋</button>
            <button data-preset="yuan" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">元</button>
            <button data-preset="ming" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">明</button>
            <button data-preset="qing" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">清</button>
            <button data-preset="modern" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">近代</button>
            <button data-preset="contemporary" class="px-2 py-1 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-white/72 transition-all duration-150">现代</button>
          </div>
        </div>
      </div>

    </div>
    <div id="workTip" class="home-work-tooltip hidden"></div>

    <script>
      const DATA_FILE = "{data_file}";
      const DATA_DETAIL_FILE = "{detail_file}";
      const STATIC_SITE = window.MAP_STORY_STATIC_SITE === true;
      const API_BASE = (typeof window.MAP_STORY_API_BASE === "string" ? window.MAP_STORY_API_BASE : "").trim();
      const resolvedApiBase = (() => {{
        if (API_BASE) return API_BASE;
        try {{
          const loc = window.location;
          const host = String(loc && loc.hostname ? loc.hostname : "").trim().toLowerCase();
          const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "::1" || host.endsWith(".localhost");
          const isPrivateIPv4 = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(host);
          const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith(".local");
          if (!loc || loc.protocol === "file:" || !isDevHost) return "";
          if (!STATIC_SITE) return "";
          const runtimeHost = host === "::1" ? "127.0.0.1" : (loc.hostname || "127.0.0.1");
          return loc.protocol + "//" + runtimeHost + ":8765";
        }} catch (_) {{
          return "";
        }}
      }})();
      const apiUrl = (path) => {{
        const rel = String(path || "").replace(/^\/+/, "");
        if (!rel) return "./";
        if (resolvedApiBase) {{
          return resolvedApiBase.replace(/\/+$/, "") + "/" + rel;
        }}
        return "./" + rel;
      }};
      const requireBackend = (actionText) => {{
        const action = String(actionText || "该功能").trim() || "该功能";
        return action + " 需要单独部署 FastAPI 后端；静态站当前仅支持浏览已生成内容。";
      }};
      const $q = document.getElementById("q");
      const $go = document.getElementById("go");
      const $goLabel = $go ? $go.querySelector(".home-search-submit-label") : null;
      const $searchValidation = document.getElementById("searchValidation");
      const $searchHint = document.getElementById("searchHint");
      const $searchSuggest = document.getElementById("searchSuggest");
      const $c = document.getElementById("c");
      const ctx = $c.getContext("2d");
      const $tip = document.getElementById("tip");
      const $mapTip = document.getElementById("mapTip");
      const $workTip = document.getElementById("workTip");
      const $h1 = document.getElementById("h1");
      const $h2 = document.getElementById("h2");
      const $sel = document.getElementById("sel");
      const $maskL = document.getElementById("maskL");
      const $maskR = document.getElementById("maskR");
      const $rail = $sel.parentElement;
      const $bands = document.getElementById("bands");
      const $mBirth = document.getElementById("mBirth");
      const $mDeath = document.getElementById("mDeath");
      const $lifeBar = document.getElementById("lifeBar");
      const $ticks = document.getElementById("ticks");
      const $activeCount = document.getElementById("activeCount");
      const $spanYear = document.getElementById("spanYear");
      const $startYearInput = document.getElementById("startYearInput");
      const $endYearInput = document.getElementById("endYearInput");
      const $timeRangeHint = document.getElementById("timeRangeHint");
      const $minLabel = document.getElementById("minLabel");
      const $maxLabel = document.getElementById("maxLabel");
      const $midLabel = document.getElementById("midLabel");
      const $tabTrack = document.getElementById("tabTrack");
      const $graphPane = document.getElementById("graphPane");
      const $tabGraph = document.getElementById("tabGraph");
      const $tabMap = document.getElementById("tabMap");
      const $mapPane = document.getElementById("mapPane");
      const $chinaMap = document.getElementById("chinaMap");
      const $provinceCurvePanel = document.getElementById("provinceCurvePanel");
      const $provinceBars = document.getElementById("provinceBars");
      const $genStatus = document.getElementById("genStatus");
      const $pixelGenPanel = document.getElementById("pixelGenPanel");
      const $pixelGenBody = document.getElementById("pixelGenBody");
      const $pixelGenLamp = document.getElementById("pixelGenLamp");
      const $pixelGenPerson = document.getElementById("pixelGenPerson");
      const $pixelGenStatusBadge = document.getElementById("pixelGenStatusBadge");
      const $pixelGenScene = document.getElementById("pixelGenScene");
      const $pixelGenSceneTitle = document.getElementById("pixelGenSceneTitle");
      const $pixelOcelotWrap = document.getElementById("pixelOcelotWrap");
      const $pixelGenStage = document.getElementById("pixelGenStage");
      const $pixelGenStatusText = document.getElementById("pixelGenStatusText");
      const $pixelGenSteps = document.getElementById("pixelGenSteps");
      const $pixelGenAgents = document.getElementById("pixelGenAgents");
      const $pixelGenSpeech = document.getElementById("pixelGenSpeech");
      const $pixelGenDetailCard = document.getElementById("pixelGenDetailCard");
      const $pixelGenDetailHint = document.getElementById("pixelGenDetailHint");
      const $pixelGenDetail = document.getElementById("pixelGenDetail");
      const $pixelGenLog = document.getElementById("pixelGenLog");
      const $pixelGenFooterText = document.getElementById("pixelGenFooterText");
      const $pixelGenPercent = document.getElementById("pixelGenPercent");
      const $pixelGenFill = document.getElementById("pixelGenFill");
      const $pixelGenToggle = document.getElementById("pixelGenToggle");
      const $pixelGenCompactText = document.getElementById("pixelGenCompactText");
      const $pixelGenOpsServe = document.getElementById("pixelGenOpsServe");
      const $pixelGenOpsGenerate = document.getElementById("pixelGenOpsGenerate");
      const $pixelGenOpsQueue = document.getElementById("pixelGenOpsQueue");
      const $pixelGenOpsDeps = document.getElementById("pixelGenOpsDeps");
      const pixelGenSceneLights = Array.from(document.querySelectorAll("#pixelGenSceneLights .pixel-progress-scene-light"));
      const STAR_OFFICE_URL = "./orange-office.html";
      const STAR_OFFICE_OPEN_IN_NEW_TAB = true;
      const YEAR_INPUT_MIN = {MIN_YEAR};
      const YEAR_INPUT_MAX = {MAX_YEAR};
      const PERSON_NAME_MAX_LENGTH = 12;
      const PERSON_NAME_ALLOWED_RE = /^[A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF\u3007\u00B7.\-'\s]+$/u;
      const $resetMap = document.getElementById("resetMap");
      const $mapStyle = document.getElementById("mapStyle");
      const $mapToolbar = document.getElementById("mapToolbar");
      const $mapSearchInput = document.getElementById("mapSearchInput");
      const $mapSearchClear = document.getElementById("mapSearchClear");
      const $mapSearchSuggest = document.getElementById("mapSearchSuggest");
      const $presetBar = document.getElementById("presetBar");

      let W = $c.width;
      let H = $c.height;
      const pad = 18;
      const syncCanvasSize = () => {{
        if (!$c || !ctx) return;
        const rect = $c.getBoundingClientRect();
        const cssW = Math.max(1, Math.round(rect.width || $c.width || 1));
        const cssH = Math.max(1, Math.round(rect.height || $c.height || 1));
        const dpr = Math.max(1, Number(window.devicePixelRatio || 1));
        W = cssW;
        H = cssH;
        const pixelW = Math.max(1, Math.round(cssW * dpr));
        const pixelH = Math.max(1, Math.round(cssH * dpr));
        if ($c.width !== pixelW || $c.height !== pixelH) {{
          $c.width = pixelW;
          $c.height = pixelH;
        }}
        try {{
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }} catch (_) {{}}
      }};
      syncCanvasSize();

      const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
      const lerp = (a, b, t) => a + (b - a) * t;
      const hash = (s) => {{
        let h = 2166136261;
        for (let i=0;i<s.length;i++) {{ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }}
        return (h >>> 0);
      }};
      const rand01 = (seed) => {{
        let x = seed >>> 0;
        x ^= x << 13; x >>>= 0;
        x ^= x >> 17; x >>>= 0;
        x ^= x << 5; x >>>= 0;
        return (x >>> 0) / 4294967296;
      }};

      const colorByYear = (y) => {{
        if (y == null) return "rgba(255,255,255,0.75)";
        if (y < 0) return "#34a853";
        if (y < 220) return "#ea4335";
        if (y < 589) return "#4285f4";
        if (y < 618) return "#fbbc04";
        if (y < 907) return "#1a73e8";
        if (y < 1368) return "#7e57c2";
        if (y < 1840) return "#0f9d58";
        if (y < 1911) return "#ff7043";
        return "#c0ca33";
      }};

      const hexToRgba = (hex, a) => {{
        const s = String(hex || "").trim();
        const alpha = Number.isFinite(Number(a)) ? Number(a) : 1;
        if (!s.startsWith("#")) return s;
        const h = s.slice(1);
        if (!(h.length === 3 || h.length === 6)) return s;
        const full = h.length === 3 ? (h[0] + h[0] + h[1] + h[1] + h[2] + h[2]) : h;
        const r = parseInt(full.slice(0, 2), 16);
        const g = parseInt(full.slice(2, 4), 16);
        const b = parseInt(full.slice(4, 6), 16);
        if (![r, g, b].every((x) => Number.isFinite(x))) return s;
        return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
      }};

      const _isInsideChina = (lat, lng) => {{
        const la = Number(lat);
        const lo = Number(lng);
        if (!Number.isFinite(la) || !Number.isFinite(lo)) return false;
        return la >= 17.5 && la <= 55.5 && lo >= 72.0 && lo <= 136.5;
      }};
      const _PI = Math.PI;
      const _A = 6378245.0;
      const _EE = 0.00669342162296594323;
      const _transformLat = (x, y) => {{
        let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * _PI) + 20.0 * Math.sin(2.0 * x * _PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(y * _PI) + 40.0 * Math.sin(y / 3.0 * _PI)) * 2.0 / 3.0;
        ret += (160.0 * Math.sin(y / 12.0 * _PI) + 320.0 * Math.sin(y * _PI / 30.0)) * 2.0 / 3.0;
        return ret;
      }};
      const _transformLng = (x, y) => {{
        let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * _PI) + 20.0 * Math.sin(2.0 * x * _PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(x * _PI) + 40.0 * Math.sin(x / 3.0 * _PI)) * 2.0 / 3.0;
        ret += (150.0 * Math.sin(x / 12.0 * _PI) + 300.0 * Math.sin(x / 30.0 * _PI)) * 2.0 / 3.0;
        return ret;
      }};
      const wgs84ToGcj02 = (lat, lng) => {{
        const la = Number(lat);
        const lo = Number(lng);
        if (!_isInsideChina(la, lo)) return {{ lat: la, lng: lo }};
        let dLat = _transformLat(lo - 105.0, la - 35.0);
        let dLng = _transformLng(lo - 105.0, la - 35.0);
        const radLat = (la / 180.0) * _PI;
        let magic = Math.sin(radLat);
        magic = 1 - _EE * magic * magic;
        const sqrtMagic = Math.sqrt(magic);
        dLat = (dLat * 180.0) / (((_A * (1 - _EE)) / (magic * sqrtMagic)) * _PI);
        dLng = (dLng * 180.0) / ((_A / sqrtMagic) * Math.cos(radLat) * _PI);
        return {{ lat: la + dLat, lng: lo + dLng }};
      }};
      const gcj02ToWgs84 = (lat, lng) => {{
        const la = Number(lat);
        const lo = Number(lng);
        if (!_isInsideChina(la, lo)) return {{ lat: la, lng: lo }};
        const mg = wgs84ToGcj02(la, lo);
        return {{ lat: la * 2.0 - mg.lat, lng: lo * 2.0 - mg.lng }};
      }};

      const esc = (s) => String(s || "").replace(/[&<>\"']/g, (c) => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);
      {shared_person_tooltip_js}
      const normalizeSearchText = (s) => {{
        let t = String(s || "").trim().toLowerCase();
        if (!t) return "";
        t = t.replace(/[·・•‧]/g, "");
        t = t.replace(/[“”"'`‘’]/g, "");
        t = t.replace(/[\s\-_./,，、:：;；()（）\[\]{{}}<>《》]+/g, "");
        t = t.replace(/[^0-9a-z\u4e00-\u9fff]+/g, "");
        return t.trim();
      }};
      const uniqStrings = (items) => {{
        const out = [];
        const seen = new Set();
        for (const item of (Array.isArray(items) ? items : [])) {{
          const s = String(item || "").trim();
          if (!s || seen.has(s)) continue;
          seen.add(s);
          out.push(s);
        }}
        return out;
      }};
      const normalizeHomeWorkTitle = (value) => {{
        let text = String(value || "").trim();
        if (!text) return "";
        text = text.replace(/[*_`]+/g, "").trim();
        if (text.startsWith("《") && text.endsWith("》") && text.length > 2) {{
          text = text.slice(1, -1).trim();
        }}
        return text.replace(/\s+/g, " ").trim();
      }};
      const cleanWorkTooltipText = (value, maxLen = 120) => {{
        let text = String(value || "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
        if (!text) return "";
        if (text.length > maxLen) text = text.slice(0, maxLen).trimEnd() + "…";
        return text;
      }};
      const resolveNodeWorkSummary = (node, title) => {{
        const cleanTitle = normalizeHomeWorkTitle(title);
        if (!cleanTitle || !node || typeof node !== "object") return null;
        const summaries = node.work_summaries && typeof node.work_summaries === "object" ? node.work_summaries : {{}};
        for (const [key, value] of Object.entries(summaries)) {{
          if (normalizeHomeWorkTitle(key) === cleanTitle && value && typeof value === "object") {{
            return value;
          }}
        }}
        return null;
      }};
      const hasWorkSummaryContent = (item) => {{
        if (!item || typeof item !== "object") return false;
        return Boolean(
          cleanWorkTooltipText(item.one_liner, 160) ||
          cleanWorkTooltipText(item.summary, 180) ||
          cleanWorkTooltipText(item.quote, 120) ||
          uniqStrings(Array.isArray(item.quotes) ? item.quotes : []).length ||
          cleanWorkTooltipText(item.era, 60) ||
          cleanWorkTooltipText(item.genre, 40) ||
          uniqStrings(Array.isArray(item.authors) ? item.authors : []).length
        );
      }};
      const buildWorkTooltipInnerHtml = (title, item) => {{
        const cleanTitle = normalizeHomeWorkTitle(title) || "相关作品";
        const authors = uniqStrings(Array.isArray(item?.authors) ? item.authors : []).join(" / ");
        const era = cleanWorkTooltipText(item?.era, 60);
        const genre = cleanWorkTooltipText(item?.genre, 40);
        const lead = cleanWorkTooltipText(item?.one_liner || item?.summary, 140);
        const quotePolicy = String(item?.quote_policy || '').trim();
        const quoteItems = uniqStrings(Array.isArray(item?.quotes) ? item.quotes : [])
          .map((value) => cleanWorkTooltipText(value, 96))
          .filter(Boolean)
          .slice(0, 3);
        const singleQuote = cleanWorkTooltipText(item?.quote, 96);
        if (!quoteItems.length && singleQuote) quoteItems.push(singleQuote);
        const rows = [
          authors ? `<div class="text-slate-500 text-[11px] mt-1">作者：${{esc(authors)}}</div>` : "",
          era ? `<div class="text-slate-500 text-[11px] mt-1">时代：${{esc(era)}}</div>` : "",
          genre ? `<div class="text-slate-500 text-[11px] mt-1">体裁：${{esc(genre)}}</div>` : "",
        ].filter(Boolean).join("");
        const leadHtml = lead ? `<div class="text-slate-700 text-[12px] mt-1 whitespace-pre-wrap">${{esc(lead)}}</div>` : "";
        const quoteHtml = quoteItems.length
          ? `<div class="text-slate-500 text-[11px] mt-1 whitespace-pre-wrap">${{quoteItems.map((quote) => esc(quote)).join("<br>")}}</div>`
          : "";
        const quotePolicyHtml = quotePolicy === "summary_only" && !quoteItems.length
          ? `<div class="text-slate-400 text-[11px] mt-1">名句展示：此类作品默认仅展示摘要</div>`
          : "";
        return `<div class="font-semibold text-slate-900">${{esc(cleanTitle)}}</div>${{leadHtml}}${{rows}}${{quoteHtml}}${{quotePolicyHtml}}`;
      }};
      const hideWorkTip = () => {{
        if ($workTip) $workTip.classList.add("hidden");
      }};
      const placeWorkTip = (clientX, clientY) => {{
        if (!$workTip) return;
        const pad = 12;
        const rect = $workTip.getBoundingClientRect();
        const vw = window.innerWidth || document.documentElement.clientWidth || 0;
        const vh = window.innerHeight || document.documentElement.clientHeight || 0;
        let left = Number(clientX) + 12;
        let top = Number(clientY) + 12;
        if (left + rect.width > vw - pad) left = Math.max(pad, Number(clientX) - rect.width - 12);
        if (top + rect.height > vh - pad) top = Math.max(pad, Number(clientY) - rect.height - 12);
        $workTip.style.left = `${{left}}px`;
        $workTip.style.top = `${{top}}px`;
      }};
      const showWorkTip = (title, item, clientX, clientY) => {{
        if (!$workTip || !hasWorkSummaryContent(item)) {{
          hideWorkTip();
          return;
        }}
        $workTip.innerHTML = buildWorkTooltipInnerHtml(title, item);
        $workTip.classList.remove("hidden");
        placeWorkTip(clientX, clientY);
      }};
      const searchSummaryLabel = (reason) => {{
        const r = String(reason || "").trim();
        if (r === "person_exact") return "本名精确";
        if (r === "alias_exact") return "别名精确";
        if (r === "foreign_exact") return "外文精确";
        if (r === "pinyin_exact") return "拼音精确";
        if (r === "person_prefix") return "本名前缀";
        if (r === "alias_prefix") return "别名前缀";
        if (r === "foreign_prefix") return "外文前缀";
        if (r === "pinyin_prefix") return "拼音前缀";
        if (r === "person_fuzzy") return "本名模糊";
        if (r === "alias_fuzzy") return "别名模糊";
        if (r === "foreign_fuzzy") return "外文模糊";
        if (r === "token_fuzzy") return "关键词模糊";
        return "相关结果";
      }};

      let nodes = [];
      let edges = [];
      let edgesAll = [];
      let neigh = [];
      let edgeMeta = new Map();
      let minYear = -800;
      let maxYear = 1840;
      let startYear = 0;
      let endYear = 1840;
      let timeWindowSignature = "";
      let dragMode = "";
      let dragStartX = 0;
      let dragStartA = 0;
      let dragStartB = 0;
      let brushStartX = 0;
      let brushStartYear = 0;
      let hover = null;
      let selectedIdx = -1;
      let selected = null;
      let spotlightIdx = -1;
      let spotlight = null;
      let _clickTimer = null;
      let homeDetailLoaded = false;
      let homeDetailPending = false;

      const detailNodeKey = (node) => {{
        if (!node || typeof node !== "object") return "";
        const person = String(node.person || "").trim();
        if (person) return "person:" + person;
        const file = String(node.file || "").trim();
        return file ? "file:" + file : "";
      }};
      const mergeNodeDetail = (node, patch) => {{
        if (!node || typeof node !== "object" || !patch || typeof patch !== "object") return node;
        Object.assign(node, patch);
        return node;
      }};
      const applyHomeDetailData = (detailData) => {{
        if (!detailData || typeof detailData !== "object") return;
        const detailNodes = Array.isArray(detailData.nodes) ? detailData.nodes : [];
        if (!detailNodes.length || !nodes.length) {{
          homeDetailLoaded = true;
          return;
        }}
        const nodeMap = new Map();
        nodes.forEach((node) => {{
          const key = detailNodeKey(node);
          if (key) nodeMap.set(key, node);
        }});
        detailNodes.forEach((detailNode) => {{
          const key = detailNodeKey(detailNode);
          if (!key || !nodeMap.has(key)) return;
          mergeNodeDetail(nodeMap.get(key), detailNode);
        }});
        homeDetailLoaded = true;
        try {{
          if ($q && String($q.value || "").trim()) renderSearchSuggest($q.value);
        }} catch (_) {{}}
        try {{ draw(); }} catch (_) {{}}
      }};
      const loadHomeDetailData = () => {{
        if (!DATA_DETAIL_FILE || homeDetailLoaded || homeDetailPending) return Promise.resolve(null);
        homeDetailPending = true;
        return fetch(DATA_DETAIL_FILE)
          .then((r) => (r && r.ok ? r.json() : null))
          .then((detail) => {{
            if (detail) applyHomeDetailData(detail);
            return detail;
          }})
          .catch(() => null)
          .finally(() => {{
            homeDetailPending = false;
          }});
      }};

      const isSpecialSunPerson = (n) => String((n && n.person) || "").trim() === "毛泽东";

      let camScale = 1.0;
      let camOffX = 0.0;
      let camOffY = 0.0;

      const worldToScreen = (x, y) => {{
        return {{
          x,
          y: y * camScale + camOffY,
        }};
      }};
      const screenToWorld = (x, y) => {{
        return {{
          x,
          y: (y - camOffY) / camScale,
        }};
      }};
      const setSelected = (n) => {{
        if (!n || typeof n._idx !== "number") {{
          pendingMapFocusPerson = "";
          selectedIdx = -1;
          selected = null;
          spotlightIdx = -1;
          spotlight = null;
          showTip(null);
          setLifeBar(null);
          draw();
          updateMapMarkers();
          return;
        }}
        selectedIdx = n._idx;
        selected = n;
        spotlightIdx = -1;
        spotlight = null;
        showTip(null);
        setLifeBar(selected);
        draw();
        updateMapMarkers();
      }};
      const setSpotlight = (n, clientX, clientY) => {{
        if (!n || typeof n._idx !== "number") {{
          spotlightIdx = -1;
          spotlight = null;
          setLifeBar(selected);
          draw();
          updateMapMarkers();
          return;
        }}
        spotlightIdx = n._idx;
        spotlight = n;
        showTip(n, clientX, clientY);
        setLifeBar(spotlight);
        draw();
        updateMapMarkers();
      }};

      const timelineSegments = () => {{
        const segments = [
          {{ a: minYear, b: Math.min(maxYear, 1840), w: 0.62 }},
          {{ a: Math.max(minYear, 1840), b: Math.min(maxYear, 1911), w: 0.16 }},
          {{ a: Math.max(minYear, 1911), b: maxYear, w: 0.22 }},
        ].filter((seg) => Number.isFinite(seg.a) && Number.isFinite(seg.b) && seg.b > seg.a);
        if (!segments.length) return [{{ a: minYear, b: maxYear, w: 1 }}];
        const totalW = segments.reduce((sum, seg) => sum + Number(seg.w || 0), 0) || 1;
        let acc = 0;
        return segments.map((seg, idx) => {{
          const w = Number(seg.w || 0) / totalW;
          const start = acc;
          const end = idx === segments.length - 1 ? 1 : (acc + w);
          acc = end;
          return {{ ...seg, start, end }};
        }});
      }};
      const toT = (year) => {{
        const y = Number(year);
        if (!Number.isFinite(y)) return 0;
        const segments = timelineSegments();
        if (y <= segments[0].a) return 0;
        for (const seg of segments) {{
          if (y <= seg.b) {{
            const local = clamp((y - seg.a) / Math.max(1, seg.b - seg.a), 0, 1);
            return seg.start + local * (seg.end - seg.start);
          }}
        }}
        return 1;
      }};
      const fromT = (t) => {{
        const tt = clamp(Number(t) || 0, 0, 1);
        const segments = timelineSegments();
        for (const seg of segments) {{
          if (tt <= seg.end || seg === segments[segments.length - 1]) {{
            const width = Math.max(1e-6, seg.end - seg.start);
            const local = clamp((tt - seg.start) / width, 0, 1);
            return Math.round(seg.a + local * (seg.b - seg.a));
          }}
        }}
        return maxYear;
      }};

      const formatYear = (y) => {{
        const yy = Math.round(Number(y));
        if (!Number.isFinite(yy)) return "";
        if (yy === 0) return "公元1";
        if (yy < 0) return `前${{-yy}}`;
        return String(yy);
      }};

      const formatYearRange = (a, b) => {{
        const hasA = a != null && Number.isFinite(Number(a));
        const hasB = b != null && Number.isFinite(Number(b));
        const dash = " \u2013 ";
        if (hasA && hasB) return `${{formatYear(a)}}${{dash}}${{formatYear(b)}}`;
        if (hasA) return `${{formatYear(a)}}${{dash}}?`;
        if (hasB) return `?${{dash}}${{formatYear(b)}}`;
        return "未知";
      }};

      const mainYear = (n) => {{
        if (!n) return null;
        const ty = n.time_year;
        if (typeof ty === "number" && Number.isFinite(ty)) return ty;
        const by = n.birth_year;
        if (typeof by === "number" && Number.isFinite(by)) return by;
        const dy = n.death_year;
        if (typeof dy === "number" && Number.isFinite(dy)) return dy;
        return null;
      }};

      const pickTickStep = (span) => {{
        const s = Math.max(1, Math.round(Number(span) || 1));
        if (s <= 60) return 5;
        if (s <= 120) return 10;
        if (s <= 240) return 20;
        if (s <= 500) return 50;
        if (s <= 900) return 100;
        if (s <= 1600) return 200;
        return 500;
      }};
      const overlapYears = (a0, a1, b0, b1) => {{
        const lo = Math.max(Math.min(Number(a0), Number(a1)), Math.min(Number(b0), Number(b1)));
        const hi = Math.min(Math.max(Number(a0), Number(a1)), Math.max(Number(b0), Number(b1)));
        return Math.max(0, hi - lo);
      }};
      const pickTickConfig = (start, end) => {{
        const span = Math.max(1, Math.round(Math.abs((Number(end) || 0) - (Number(start) || 0))));
        let step = pickTickStep(span);
        const recentRatio = overlapYears(start, end, 1840, maxYear) / span;
        const contemporaryRatio = overlapYears(start, end, 1911, maxYear) / span;
        if (contemporaryRatio >= 0.7) {{
          if (span <= 90) step = Math.max(step, 20);
          else if (span <= 180) step = Math.max(step, 25);
          else if (span <= 360) step = Math.max(step, 50);
          else if (span <= 700) step = Math.max(step, 100);
        }} else if (recentRatio >= 0.55) {{
          if (span <= 80) step = Math.max(step, 15);
          else if (span <= 160) step = Math.max(step, 25);
          else if (span <= 320) step = Math.max(step, 50);
          else if (span <= 620) step = Math.max(step, 100);
        }}
        const maxLabels = contemporaryRatio >= 0.7 ? 5 : (recentRatio >= 0.55 ? 6 : 9);
        const minPxPerLabel = contemporaryRatio >= 0.7 ? 108 : (recentRatio >= 0.55 ? 88 : 56);
        return {{ step, maxLabels, minPxPerLabel }};
      }};

      const formatTickLabel = (y, span, step) => {{
        let yy = Math.round(Number(y));
        if (!Number.isFinite(yy)) return "";
        if (yy === 0) yy = 1;
        if (span >= 1200 || step >= 200) {{
          if (yy < 0) {{
            const c = Math.floor(((-yy) - 1) / 100) + 1;
            return `前${{c}}世纪`;
          }}
          const c = Math.floor((yy - 1) / 100) + 1;
          return `${{c}}世纪`;
        }}
        return formatYear(yy);
      }};

      const renderTicks = () => {{
        if (!$ticks) return;
        const span = Math.max(1, endYear - startYear);
        const tickConfig = pickTickConfig(startYear, endYear);
        const step = tickConfig.step;
        const r = $ticks.getBoundingClientRect();
        const w = r.width || 1;
        const density = Math.max(1, Math.floor((span / step)));
        const pxPerStep = Math.max(1, Math.abs(clamp(toT(startYear + step), 0, 1) - clamp(toT(startYear), 0, 1)) * w);
        const maxLabels = tickConfig.maxLabels;
        const minPxPerLabel = tickConfig.minPxPerLabel;
        let labelEvery = Math.max(1, Math.ceil(density / maxLabels));
        labelEvery = Math.max(labelEvery, Math.ceil(minPxPerLabel / Math.max(1, pxPerStep)));
        let y0 = Math.floor(startYear / step) * step;
        if (y0 > startYear) y0 -= step;
        let html = "";
        let idx = 0;
        for (let y = y0; y <= endYear + step; y += step) {{
          if (y < startYear - step) continue;
          if (y > endYear + step) break;
          const left = clamp(toT(y), 0, 1) * w;
          const major = (idx % labelEvery) === 0;
          const h = major ? 16 : 10;
          const op = major ? 0.32 : 0.14;
          html += `<div style="position:absolute;left:${{left.toFixed(2)}}px;bottom:6px;width:1px;height:${{h}}px;background:rgba(255,255,255,${{op}})"></div>`;
          if (major) {{
            const lab = formatTickLabel(y, span, step);
            if (lab) {{
              html += `<div style="position:absolute;left:${{left.toFixed(2)}}px;top:2px;transform:translateX(-50%);font-size:10px;color:rgba(255,255,255,0.56);white-space:nowrap">${{esc(lab)}}</div>`;
            }}
          }}
          idx += 1;
        }}
        $ticks.innerHTML = html;
      }};

      const setLifeBar = (n) => {{
        if (!$lifeBar) return;
        const pick = n && typeof n === "object" ? n : null;
        const b = pick ? pick.birth_year : null;
        const d = pick ? pick.death_year : null;
        if (b == null && d == null) {{
          $lifeBar.classList.add("hidden");
          return;
        }}
        const m = railMetrics();
        const w = m.innerW || 1;
        let a = (b != null) ? b : d;
        let z = (d != null) ? d : b;
        if (a == null || z == null) {{
          $lifeBar.classList.add("hidden");
          return;
        }}
        if (a > z) {{ const t = a; a = z; z = t; }}
        const t1 = clamp(toT(a), 0, 1);
        const t2 = clamp(toT(z), 0, 1);
        const minW = 6 / w;
        const tt2 = Math.max(t2, t1 + minW);
        $lifeBar.style.left = `${{(m.inset + t1 * w).toFixed(2)}}px`;
        $lifeBar.style.width = `${{Math.max(6, (tt2 - t1) * w).toFixed(2)}}px`;
        $lifeBar.classList.remove("hidden");
      }};

      const zoomToFitWindowNodes = () => {{
        if (!nodes || !nodes.length) return;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        let c = 0;
        for (const n of nodes) {{
          if (!inWindow(n)) continue;
          if (typeof n.x !== "number" || typeof n.y !== "number") continue;
          minX = Math.min(minX, n.x);
          minY = Math.min(minY, n.y);
          maxX = Math.max(maxX, n.x);
          maxY = Math.max(maxY, n.y);
          c += 1;
        }}
        if (c < 2 || !Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) return;
        const bw = Math.max(10, maxX - minX);
        const bh = Math.max(10, maxY - minY);
        const margin = 36;
        const sx = (W - margin * 2) / bw;
        const sy = (H - margin * 2) / bh;
        camScale = clamp(Math.min(sx, sy), 0.35, 3.8);
        camOffX = (W - (minX + maxX) * camScale) / 2;
        camOffY = (H - (minY + maxY) * camScale) / 2;
      }};

      const getPresetRanges = () => ({{
        all: [minYear, maxYear],
        preqin: [-800, -221],
        qin: [-221, -206],
        han: [-206, 220],
        weijin: [220, 589],
        sui: [581, 618],
        tang: [618, 907],
        song: [960, 1279],
        yuan: [1271, 1368],
        ming: [1368, 1644],
        qing: [1644, 1840],
        modern: [1840, 1911],
        contemporary: [1911, maxYear],
      }});
      const syncPresetButtons = () => {{
        if (!$presetBar) return;
        const presets = getPresetRanges();
        let activeKey = "";
        for (const [key, rawRange] of Object.entries(presets)) {{
          const a = clamp(rawRange[0], minYear, maxYear);
          let b = clamp(rawRange[1], minYear, maxYear);
          if (a >= b) b = clamp(a + 1, minYear, maxYear);
          if (startYear === a && endYear === b) {{
            activeKey = key;
            break;
          }}
        }}
        const buttons = $presetBar.querySelectorAll("button[data-preset]");
        buttons.forEach((btn) => {{
          const key = String(btn.getAttribute("data-preset") || "");
          const active = key === activeKey;
          btn.style.background = active ? "linear-gradient(135deg, rgba(59,130,246,0.52), rgba(34,197,94,0.42))" : "rgba(255,255,255,0.10)";
          btn.style.borderColor = active ? "rgba(255,255,255,0.54)" : "rgba(255,255,255,0.15)";
          btn.style.color = active ? "rgba(255,255,255,0.98)" : "rgba(255,255,255,0.72)";
          btn.style.fontWeight = active ? "700" : "500";
          btn.style.transform = active ? "translateY(-1px)" : "translateY(0)";
          btn.style.boxShadow = active ? "0 0 0 1px rgba(255,255,255,0.12) inset, 0 10px 26px rgba(37,99,235,0.28), 0 0 18px rgba(34,197,94,0.20)" : "none";
        }});
      }};
      const railMetrics = () => {{
        const r = $rail.getBoundingClientRect();
        const outerW = r.width || 1;
        const inset = 18;
        const innerW = Math.max(1, outerW - inset * 2);
        return {{ outerW, innerW, inset }};
      }};
      const setSearchValidation = (txt) => {{
        if (!$searchValidation) return;
        const msg = String(txt || "").trim();
        if (!msg) {{
          $searchValidation.textContent = "";
          $searchValidation.classList.add("hidden");
          return;
        }}
        $searchValidation.textContent = msg;
        $searchValidation.classList.remove("hidden");
      }};
      const setTimeRangeHint = (txt) => {{
        if (!$timeRangeHint) return;
        const msg = String(txt || "").trim();
        if (!msg) {{
          $timeRangeHint.textContent = "";
          $timeRangeHint.classList.add("hidden");
          return;
        }}
        $timeRangeHint.textContent = msg;
        $timeRangeHint.classList.remove("hidden");
      }};
      const validatePersonInput = (rawValue, options = {{}}) => {{
        const allowEmpty = !!(options && options.allowEmpty);
        const normalized = String(rawValue || "").replace(/\s+/g, " ").trim();
        if (!normalized) {{
          return {{
            value: "",
            hasValue: false,
            ok: allowEmpty,
            reason: allowEmpty ? "" : "请输入历史人物姓名",
          }};
        }}
        if (normalized.length > PERSON_NAME_MAX_LENGTH) {{
          return {{
            value: normalized,
            hasValue: true,
            ok: false,
            reason: "人物姓名最多支持 12 个字符",
          }};
        }}
        if (!PERSON_NAME_ALLOWED_RE.test(normalized)) {{
          return {{
            value: normalized,
            hasValue: true,
            ok: false,
            reason: "请输入 12 字以内的历史人物姓名，仅支持汉字、字母和常见人名连接符",
          }};
        }}
        if (!/[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFFA-Za-z]/u.test(normalized)) {{
          return {{
            value: normalized,
            hasValue: true,
            ok: false,
            reason: "请输入有效的历史人物姓名",
          }};
        }}
        return {{
          value: normalized,
          hasValue: true,
          ok: true,
          reason: "",
        }};
      }};
      const syncSearchActionState = (options = {{}}) => {{
        const showReason = !!(options && options.showReason);
        const generating = !!(options && options.generating);
        const validation = validatePersonInput($q ? $q.value : "", {{ allowEmpty: true }});
        if (generating) {{
          if ($go) $go.disabled = true;
          return validation;
        }}
        const disabled = !validation.hasValue || !validation.ok;
        if ($go) $go.disabled = disabled;
        if (!validation.hasValue) {{
          setSearchValidation("");
        }} else if (!validation.ok && showReason) {{
          setSearchValidation(validation.reason);
        }} else if (validation.ok) {{
          setSearchValidation("");
        }}
        return validation;
      }};
      const normalizeYearInputRange = (a, b) => {{
        let start = Math.round(a);
        let end = Math.round(b);
        const notes = [];
        if (start > end) {{
          const temp = start;
          start = end;
          end = temp;
          notes.push("起止年份已自动按先后顺序调整");
        }}
        const rawStart = start;
        const rawEnd = end;
        start = clamp(start, YEAR_INPUT_MIN, YEAR_INPUT_MAX);
        end = clamp(end, YEAR_INPUT_MIN, YEAR_INPUT_MAX);
        if (start !== rawStart || end !== rawEnd) {{
          notes.push(`年份范围已限制在 ${{YEAR_INPUT_MIN}} 到 ${{YEAR_INPUT_MAX}}`);
        }}
        if (start === end) {{
          end = clamp(start + 1, YEAR_INPUT_MIN, YEAR_INPUT_MAX);
          if (end === start) start = clamp(end - 1, YEAR_INPUT_MIN, YEAR_INPUT_MAX);
          notes.push("时间窗口至少需要 1 年跨度");
        }}
        return {{
          start,
          end,
          message: notes.join("；"),
        }};
      }};
      const setYearInputs = () => {{
        if ($startYearInput) $startYearInput.value = String(startYear);
        if ($endYearInput) $endYearInput.value = String(endYear);
      }};
      const applyYearInputs = () => {{
        const a = $startYearInput ? Number($startYearInput.value) : NaN;
        const b = $endYearInput ? Number($endYearInput.value) : NaN;
        if (!Number.isFinite(a) || !Number.isFinite(b)) {{
          setTimeRangeHint(`请输入 ${{YEAR_INPUT_MIN}} 到 ${{YEAR_INPUT_MAX}} 之间的年份`);
          setYearInputs();
          return;
        }}
        const normalized = normalizeYearInputRange(a, b);
        startYear = normalized.start;
        endYear = normalized.end;
        setTimeRangeHint(normalized.message);
        setHandles();
        updateActiveCount();
        updateCoordCount();
        updateMapMarkers();
        draw();
      }};

      const handlePosPx = () => {{
        const m = railMetrics();
        const x1 = m.inset + toT(startYear) * m.innerW;
        const x2 = m.inset + toT(endYear) * m.innerW;
        return {{ x1, x2, w: m.outerW }};
      }};

      const setHoverMarkers = (n) => {{
        if (!n) {{
          $mBirth.classList.add("hidden");
          $mDeath.classList.add("hidden");
          return;
        }}
        const m = railMetrics();
        const show = (el, year) => {{
          if (year == null) {{
            el.classList.add("hidden");
            return;
          }}
          const t = clamp(toT(year), 0, 1);
          el.style.left = `${{(m.inset + t * m.innerW).toFixed(2)}}px`;
          el.classList.remove("hidden");
        }};
        show($mBirth, n.birth_year);
        show($mDeath, n.death_year);
      }};

      const setHandles = () => {{
        const m = railMetrics();
        const t1 = clamp(toT(startYear), 0, 1);
        const t2 = clamp(toT(endYear), 0, 1);
        const leftPx = m.inset + t1 * m.innerW;
        const rightPx = m.inset + t2 * m.innerW;
        $h1.style.left = `${{(leftPx - 7).toFixed(2)}}px`;
        $h2.style.left = `${{(rightPx - 7).toFixed(2)}}px`;
        $sel.style.left = `${{leftPx.toFixed(2)}}px`;
        $sel.style.width = `${{Math.max(1, rightPx - leftPx).toFixed(2)}}px`;
        if ($maskL) {{
          $maskL.style.left = `${{m.inset.toFixed(2)}}px`;
          $maskL.style.width = `${{Math.max(0, leftPx - m.inset).toFixed(2)}}px`;
        }}
        if ($maskR) {{
          $maskR.style.left = `${{rightPx.toFixed(2)}}px`;
          $maskR.style.width = `${{Math.max(0, (m.outerW - m.inset) - rightPx).toFixed(2)}}px`;
        }}
        $spanYear.textContent = String(Math.max(0, endYear - startYear));
        setYearInputs();
        $minLabel.textContent = formatYear(minYear);
        $maxLabel.textContent = formatYear(maxYear);
        $midLabel.textContent = formatYear(Math.round((startYear + endYear) / 2));
        renderTicks();
        syncPresetButtons();
        setLifeBar(spotlight || selected);
        persistTimeWindow();
        scheduleMapFit();
        updateProvinceBars();
      }};

      const inWindow = (n) => {{
        const y = mainYear(n);
        if (y == null) return false;
        return y >= startYear && y <= endYear;
      }};

      const updateActiveCount = () => {{
        let c = 0;
        for (const n of nodes) {{
          if (inWindow(n)) c += 1;
        }}
        if ($activeCount) $activeCount.textContent = String(c);
      }};

      const updateCoordCount = () => {{
        let c = 0;
        for (const n of nodes) {{
          if (typeof n.birth_lat === "number" && typeof n.birth_lng === "number") c += 1;
        }}
      }};

      const provinceOf = (n) => {{
        const raw = String((n && (n.birthplace_modern || n.birthplace || n.birthplace_raw)) || "").trim();
        if (!raw) return "";
        const s = raw.replace(/^今\s*/g, "");
        const m = s.match(/(北京市|天津市|上海市|重庆市|香港特别行政区|澳门特别行政区|台湾省|内蒙古自治区|广西壮族自治区|宁夏回族自治区|新疆维吾尔自治区|西藏自治区|黑龙江省|吉林省|辽宁省|河北省|山西省|陕西省|山东省|河南省|江苏省|浙江省|安徽省|江西省|福建省|广东省|海南省|四川省|贵州省|云南省|湖北省|湖南省|甘肃省|青海省)/);
        if (m) {{
          const t = String(m[1] || "").trim();
          if (t.endsWith("省")) return t.slice(0, -1);
          if (t.endsWith("市")) return t.slice(0, -1);
          if (t.endsWith("特别行政区")) return t.replace(/特别行政区$/, "");
          if (t.endsWith("自治区")) return t.replace(/自治区$/, "");
          return t;
        }}
        const m2 = s.match(/(北京|天津|上海|重庆|香港|澳门|台湾|内蒙古|广西|宁夏|新疆|西藏|黑龙江|吉林|辽宁|河北|山西|陕西|山东|河南|江苏|浙江|安徽|江西|福建|广东|海南|四川|贵州|云南|湖北|湖南|甘肃|青海)/);
        if (m2) return String(m2[1] || "").trim();
        return "";
      }};

      const cityOf = (n) => {{
        const raw = String((n && (n.birthplace_modern || n.birthplace || n.birthplace_raw)) || "").trim();
        if (!raw) return "";
        // Strip leading "今"; take first segment before separators; remove parentheses.
        let s = raw.replace(/^今\s*/g, "");
        s = s.split(/[；;，,、]/)[0].replace(/[（(].*?[）)]/g, "").trim();
        // After province prefix (xx省 / xx市 / xx自治区 / xx特别行政区), pull out the city / 地级 / 县级 token.
        const m = s.match(/(?:[^省市区]+?省|[^省市区]+?自治区|[^省市区]+?特别行政区)?\s*([\u4e00-\u9fa5]{{2,}}?(?:市|地区|盟|州|县|区))/);
        if (m && m[1]) {{
          return String(m[1]).trim();
        }}
        // If string itself ends with 市/县/州/区/地区/盟, return the whole short token.
        const m2 = s.match(/^([\u4e00-\u9fa5]{{2,}}?(?:市|地区|盟|州|县|区))$/);
        if (m2 && m2[1]) return String(m2[1]).trim();
        return "";
      }};

      let mapSearchQuery = "";
      let mapSearchSuggestIdx = -1;
      const mapSearchHighlightSet = new Set();
      const _normalizeMapSearch = (raw) => {{
        const txt = String(raw == null ? "" : raw).trim();
        if (!txt) return "";
        return txt.replace(/^今\s*/g, "").replace(/(省|市|地区|盟|州|县|区|特别行政区|自治区)$/g, "").trim();
      }};
      const matchPersonByPlace = (n, qNorm) => {{
        if (!qNorm) return false;
        const raw = String((n && (n.birthplace_modern || n.birthplace || n.birthplace_raw)) || "");
        if (!raw) return false;
        const hay = raw.replace(/\s+/g, "");
        if (hay.indexOf(qNorm) >= 0) return true;
        const prov = provinceOf(n);
        if (prov && prov.indexOf(qNorm) >= 0) return true;
        const city = cityOf(n);
        if (city && _normalizeMapSearch(city).indexOf(qNorm) >= 0) return true;
        return false;
      }};
      const collectMapSearchMatches = (qRaw, limit) => {{
        const qNorm = _normalizeMapSearch(qRaw);
        const out = [];
        if (!qNorm) return out;
        const cap = Math.max(1, Number(limit) || 30);
        for (const n of nodes) {{
          if (!n) continue;
          if (!matchPersonByPlace(n, qNorm)) continue;
          out.push(n);
          if (out.length >= cap) break;
        }}
        return out;
      }};
      const _hexColorByYearOrDefault = (n) => {{
        try {{
          const c = colorByYear(n && n.time_year);
          return c || "rgba(148,163,184,0.85)";
        }} catch (_) {{
          return "rgba(148,163,184,0.85)";
        }}
      }};
      const renderMapSearchSuggest = () => {{
        if (!$mapSearchSuggest) return;
        const matches = collectMapSearchMatches(mapSearchQuery, 30);
        if (!matches.length) {{
          if (!mapSearchQuery) {{
            $mapSearchSuggest.classList.add("hidden");
            $mapSearchSuggest.innerHTML = "";
            return;
          }}
          $mapSearchSuggest.classList.remove("hidden");
          $mapSearchSuggest.innerHTML = '<div class="px-3 py-2 text-[11px] text-white/55">未匹配到人物</div>';
          return;
        }}
        const parts = [];
        for (let i = 0; i < matches.length; i += 1) {{
          const n = matches[i];
          const active = i === mapSearchSuggestIdx ? "bg-white/15" : "hover:bg-white/10";
          const color = _hexColorByYearOrDefault(n);
          const place = String(n.birthplace_modern || n.birthplace || n.birthplace_raw || "").replace(/^今\s*/g, "");
          parts.push(
            '<div data-msi="' + String(i) + '" data-mperson="' + esc(String(n.person || "")) + '" class="cursor-pointer px-3 py-1.5 ' + active + ' flex items-center gap-2">' +
              '<span class="inline-block w-2 h-2 rounded-full flex-shrink-0" style="background:' + esc(String(color)) + '"></span>' +
              '<span class="text-[12px] text-white/90 truncate">' + esc(String(n.person || "")) + '</span>' +
              '<span class="ml-auto text-[10px] text-white/55 truncate max-w-[120px]" title="' + esc(place) + '">' + esc(place) + '</span>' +
            '</div>'
          );
        }}
        $mapSearchSuggest.innerHTML = parts.join("");
        $mapSearchSuggest.classList.remove("hidden");
      }};
      const recomputeMapSearchHighlights = () => {{
        mapSearchHighlightSet.clear();
        const qNorm = _normalizeMapSearch(mapSearchQuery);
        if (!qNorm) return;
        for (const n of nodes) {{
          if (n && typeof n._idx === "number" && matchPersonByPlace(n, qNorm)) {{
            mapSearchHighlightSet.add(n._idx);
          }}
        }}
      }};
      const focusMapOnSearchMatch = () => {{
        if (!amap || currentTab !== "map") return;
        const matches = collectMapSearchMatches(mapSearchQuery, 200);
        if (!matches.length) return;
        try {{
          const positions = [];
          for (const n of matches) {{
            const latW = (typeof n.birth_lat_wgs84 === "number") ? n.birth_lat_wgs84 : n.birth_lat;
            const lngW = (typeof n.birth_lng_wgs84 === "number") ? n.birth_lng_wgs84 : n.birth_lng;
            if (!Number.isFinite(latW) || !Number.isFinite(lngW)) continue;
            const p = wgs84ToGcj02(latW, lngW);
            if (Number.isFinite(p.lat) && Number.isFinite(p.lng)) positions.push([p.lng, p.lat]);
          }}
          if (!positions.length) return;
          if (positions.length === 1) {{
            const z = Math.max(7, Number(amap.getZoom ? amap.getZoom() : 7) || 7);
            amap.setZoomAndCenter(Math.min(10, z), positions[0]);
            mapCameraTouched = true;
            return;
          }}
          if (window.AMap && window.AMap.Bounds) {{
            let minLng = positions[0][0], maxLng = positions[0][0];
            let minLat = positions[0][1], maxLat = positions[0][1];
            for (const pos of positions) {{
              if (pos[0] < minLng) minLng = pos[0];
              if (pos[0] > maxLng) maxLng = pos[0];
              if (pos[1] < minLat) minLat = pos[1];
              if (pos[1] > maxLat) maxLat = pos[1];
            }}
            const bounds = new window.AMap.Bounds([minLng, minLat], [maxLng, maxLat]);
            try {{ amap.setBounds(bounds, false, [56, 56, 56, 56]); }} catch (_) {{}}
            mapCameraTouched = true;
          }}
        }} catch (_) {{}}
      }};
      const applyMapSearch = (raw, opts) => {{
        const next = String(raw == null ? "" : raw);
        const same = next === mapSearchQuery;
        mapSearchQuery = next;
        if ($mapSearchClear) {{
          if (mapSearchQuery) $mapSearchClear.classList.remove("hidden");
          else $mapSearchClear.classList.add("hidden");
        }}
        recomputeMapSearchHighlights();
        mapSearchSuggestIdx = -1;
        renderMapSearchSuggest();
        if (currentTab === "map") {{
          updateMapMarkers();
          if (opts && opts.fit && !same) focusMapOnSearchMatch();
        }}
      }};

      const _curvePathFromPoints = (pts) => {{
        if (!Array.isArray(pts) || pts.length < 2) return "";
        const p = pts.map((x) => [Number(x[0]), Number(x[1])]).filter((x) => Number.isFinite(x[0]) && Number.isFinite(x[1]));
        if (p.length < 2) return "";
        const cr = (p0, p1, p2, p3) => {{
          const x1 = p1[0] + (p2[0] - p0[0]) / 6;
          const y1 = p1[1] + (p2[1] - p0[1]) / 6;
          const x2 = p2[0] - (p3[0] - p1[0]) / 6;
          const y2 = p2[1] - (p3[1] - p1[1]) / 6;
          return [x1, y1, x2, y2, p2[0], p2[1]];
        }};
        let d = `M ${{p[0][0].toFixed(2)}} ${{p[0][1].toFixed(2)}}`;
        for (let i = 0; i < p.length - 1; i += 1) {{
          const p0 = p[Math.max(0, i - 1)];
          const p1 = p[i];
          const p2 = p[i + 1];
          const p3 = p[Math.min(p.length - 1, i + 2)];
          const c = cr(p0, p1, p2, p3);
          d += ` C ${{c[0].toFixed(2)}} ${{c[1].toFixed(2)}}, ${{c[2].toFixed(2)}} ${{c[3].toFixed(2)}}, ${{c[4].toFixed(2)}} ${{c[5].toFixed(2)}}`;
        }}
        return d;
      }};

      const updateProvinceBars = () => {{
        if (!$provinceBars) return;
        const counts = new Map();
        let total = 0;
        for (const n of nodes) {{
          if (!inWindow(n)) continue;
          const prov = provinceOf(n);
          if (!prov) continue;
          total += 1;
          counts.set(prov, (counts.get(prov) || 0) + 1);
        }}
        const items = Array.from(counts.entries()).sort((a, b) => (b[1] - a[1]) || String(a[0]).localeCompare(String(b[0])));
        const top = items.slice(0, 5);
        const maxV = top.reduce((m, it) => Math.max(m, Number(it[1] || 0)), 1) || 1;
        const parts = [];
        for (const [prov, v0] of top) {{
          const v = Number(v0 || 0);
          const pct = Math.max(2, Math.round((v / maxV) * 100));
          parts.push(
            '<div class=\"flex items-center gap-2 mb-1\">' +
              '<div class=\"w-10 text-[11px] text-white/70 truncate\" title=\"' + esc(String(prov)) + '\">' + esc(String(prov)) + '</div>' +
              '<div class=\"flex-1\">' +
                '<div class=\"h-[10px] rounded-full bg-white/10 border border-white/10 overflow-hidden\">' +
                  '<div class=\"h-full rounded-full\" style=\"width:' + String(pct) + '%;background:rgba(34,197,94,0.70)\"></div>' +
                '</div>' +
              '</div>' +
              '<div class=\"w-10 text-right text-[11px] text-white/70\">' + esc(String(v)) + '</div>' +
            '</div>'
          );
        }}
        $provinceBars.innerHTML = parts.join('') || '<div class=\"text-[11px] text-white/55\">当前时间窗无中国人物</div>';
      }};

      const renderBands = () => {{
        if (!$bands) return;
        const bands = [
          {{ name: "春秋战国", a: -800, b: -221 }},
          {{ name: "秦", a: -221, b: -206 }},
          {{ name: "汉", a: -206, b: 220 }},
          {{ name: "魏晋南北", a: 220, b: 589 }},
          {{ name: "隋", a: 581, b: 618 }},
          {{ name: "唐", a: 618, b: 907 }},
          {{ name: "宋", a: 960, b: 1279 }},
          {{ name: "元", a: 1271, b: 1368 }},
          {{ name: "明", a: 1368, b: 1644 }},
          {{ name: "清", a: 1644, b: 1840 }},
          {{ name: "近代", a: 1840, b: 1911 }},
          {{ name: "现代", a: 1911, b: 2000 }},
        ];
        const bandColors = [
          "rgba(56,189,248,0.12)",
          "rgba(34,197,94,0.10)",
          "rgba(239,68,68,0.10)",
          "rgba(96,165,250,0.10)",
          "rgba(245,158,11,0.10)",
          "rgba(168,85,247,0.10)",
          "rgba(16,185,129,0.10)",
          "rgba(249,115,22,0.10)",
          "rgba(234,179,8,0.10)",
        ];
        const pieces = [];
        for (let i = 0; i < bands.length; i++) {{
          const b = bands[i];
          const l = clamp(toT(b.a), 0, 1);
          const r = clamp(toT(b.b), 0, 1);
          if (r <= 0 || l >= 1) continue;
          const left = (l * 100).toFixed(4) + "%";
          const width = ((r - l) * 100).toFixed(4) + "%";
          const bg = bandColors[i % bandColors.length];
          pieces.push(`<div style="position:absolute;left:${{left}};width:${{width}};top:0;bottom:0;display:flex;align-items:center;justify-content:center;overflow:visible;background:${{bg}};border-right:1px solid rgba(255,255,255,0.12);"><span style="white-space:nowrap;padding:0 6px;text-shadow:0 1px 0 rgba(0,0,0,0.25)">${{esc(b.name)}}</span></div>`);
        }}
        $bands.innerHTML = pieces.join("");
        $bands.style.position = "absolute";
      }};

      const draw = () => {{
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = "rgba(0,0,0,0)";
        ctx.fillRect(0, 0, W, H);

        ctx.globalCompositeOperation = "source-over";
        const selectedSet = new Set();
        if (selectedIdx >= 0 && neigh[selectedIdx]) {{
          selectedSet.add(selectedIdx);
          for (const j of (neigh[selectedIdx] || [])) selectedSet.add(j);
        }}
        if (edges.length) {{
          ctx.lineWidth = 1;
          for (const e of edges) {{
            const typ = String((e && e.type) || "bio").trim().toLowerCase();
            const conf = Number((e && (e.confidence ?? e.conf)) ?? 0);
            const c = Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : 0;
            const baseA = 0.05 + c * 0.22;
            ctx.globalAlpha = Math.max(0.04, Math.min(0.20, baseA));
            ctx.strokeStyle = typ === "manual"
              ? "rgba(147,197,253,0.70)"
              : (typ === "same_book" ? "rgba(148,163,184,0.55)" : "rgba(255,255,255,0.55)");
            const a = nodes[e.a];
            const b = nodes[e.b];
            if (!a || !b) continue;
            const pa = worldToScreen(a.x, a.y);
            const pb = worldToScreen(b.x, b.y);
            ctx.beginPath();
            ctx.moveTo(pa.x, pa.y);
            ctx.lineTo(pb.x, pb.y);
            ctx.stroke();
          }}
          ctx.globalAlpha = 1.0;

          for (const e of edges) {{
            const typ = String((e && e.type) || "bio").trim().toLowerCase();
            const conf = Number((e && (e.confidence ?? e.conf)) ?? 0);
            const c = Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : 0;
            const baseA = 0.12 + c * 0.35;
            ctx.globalAlpha = Math.max(0.10, Math.min(0.38, baseA));
            ctx.strokeStyle = typ === "manual"
              ? "rgba(147,197,253,0.92)"
              : (typ === "same_book" ? "rgba(203,213,225,0.78)" : "rgba(255,255,255,0.78)");
            const a = nodes[e.a];
            const b = nodes[e.b];
            if (!a || !b) continue;
            if (!(inWindow(a) && inWindow(b))) continue;
            const pa = worldToScreen(a.x, a.y);
            const pb = worldToScreen(b.x, b.y);
            ctx.beginPath();
            ctx.moveTo(pa.x, pa.y);
            ctx.lineTo(pb.x, pb.y);
            ctx.stroke();
          }}
          ctx.globalAlpha = 1.0;

          const hiIdx = selectedIdx >= 0
            ? selectedIdx
            : (spotlightIdx >= 0
                ? spotlightIdx
                : (hover && typeof hover._idx === "number" ? hover._idx : -1));
          if (hiIdx >= 0) {{
            const ns = neigh[hiIdx] || [];
            ctx.strokeStyle = "rgba(34,197,94,0.85)";
            ctx.lineWidth = 1.8;
            ctx.globalAlpha = 0.70;
            for (const j of ns) {{
              const a = nodes[hiIdx];
              const b = nodes[j];
              if (!a || !b) continue;
              if (!(inWindow(a) && inWindow(b))) continue;
              const pa = worldToScreen(a.x, a.y);
              const pb = worldToScreen(b.x, b.y);
              ctx.beginPath();
              ctx.moveTo(pa.x, pa.y);
              ctx.lineTo(pb.x, pb.y);
              ctx.stroke();
            }}
            ctx.globalAlpha = 1.0;
            ctx.lineWidth = 1;

            if (selectedIdx >= 0) {{
              ctx.save();
              ctx.font = "11px system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              for (let ii = 0; ii < ns.length; ii += 1) {{
                const j = ns[ii];
                const a = nodes[hiIdx];
                const b = nodes[j];
                if (!a || !b) continue;
                if (!(inWindow(a) && inWindow(b))) continue;
                const lo = Math.min(hiIdx, j);
                const hi = Math.max(hiIdx, j);
                const meta = edgeMeta.get(`${{lo}},${{hi}}`) || null;
                const label = meta && meta.label ? String(meta.label) : "";
                if (!label) continue;
                const pa = worldToScreen(a.x, a.y);
                const pb = worldToScreen(b.x, b.y);
                const mx = (pa.x + pb.x) / 2;
                const my = (pa.y + pb.y) / 2;
                const dx = pb.x - pa.x;
                const dy = pb.y - pa.y;
                const len = Math.hypot(dx, dy) || 1;
                const nx = (-dy) / len;
                const ny = dx / len;
                const sign = (ii % 2 === 0) ? 1 : -1;
                const ox = nx * 10 * sign;
                const oy = ny * 10 * sign;
                const x = mx + ox;
                const y = my + oy;
                ctx.lineWidth = 3;
                ctx.strokeStyle = "rgba(15,23,42,0.55)";
                ctx.fillStyle = "rgba(255,255,255,0.88)";
                try {{ ctx.strokeText(label, x, y); }} catch (_) {{}}
                ctx.fillText(label, x, y);
              }}
              ctx.restore();
            }}
          }}
        }}

        ctx.globalCompositeOperation = "source-over";
        const drawForeignRect = (pt, size, fillStyle, strokeStyle, lineAlpha, activeGlowAlpha) => {{
          const w = size * 2;
          const h = size * 2;
          const x = pt.x - w / 2;
          const y = pt.y - h / 2;
          ctx.fillStyle = fillStyle;
          ctx.fillRect(x, y, w, h);
          ctx.strokeStyle = strokeStyle;
          ctx.globalAlpha = lineAlpha;
          ctx.lineWidth = Math.max(0.9, 1.1 * camScale);
          ctx.strokeRect(x + 0.4, y + 0.4, Math.max(0.8, w - 0.8), Math.max(0.8, h - 0.8));
          if (activeGlowAlpha > 0) {{
            ctx.strokeStyle = "rgba(255,255,255,0.22)";
            ctx.globalAlpha = activeGlowAlpha;
            ctx.lineWidth = 1 * camScale;
            ctx.strokeRect(x - 2.2 * camScale, y - 2.2 * camScale, w + 4.4 * camScale, h + 4.4 * camScale);
          }}
        }};
        for (const n of nodes) {{
          const p = (typeof n.p === "number") ? clamp(n.p, 0, 1) : (inWindow(n) ? 1 : 0);
          const active = p > 0.55;
          const specialSun = isSpecialSunPerson(n);
          const foreignPerson = isForeignPerson(n);
          let r = (4.4 + p * 2.8) * camScale;
          let alpha = 0.10 + p * 0.88;
          let col = p > 0 ? colorByYear(mainYear(n)) : "rgba(255,255,255,0.30)";
          const i = n._idx;
          const hovered = hover && hover.person === n.person;
          const selectedHere = selected && selected.person === n.person;
          const spotlightHere = (selectedIdx < 0) && spotlight && spotlight.person === n.person;
          if (selectedIdx >= 0) {{
            if (!selectedSet.has(i)) {{
              alpha *= 0.12;
              col = "rgba(255,255,255,0.22)";
            }} else {{
              alpha = Math.max(alpha, 0.70);
            }}
          }}
          if (hovered) {{
            r = 9.2 * camScale;
            alpha = 1.0;
            col = "#fbbf24";
          }}
          if (selectedHere) {{
            r = 10.5 * camScale;
            alpha = 1.0;
            col = "#fbbf24";
          }}
          if (spotlightHere) {{
            r = 11.0 * camScale;
            alpha = 1.0;
            col = "#fbbf24";
          }}
          const pt = worldToScreen(n.x, n.y);
          if (specialSun) {{
            const rayOuter = r + 4.2 * camScale;
            const rayInner = r + 1.1 * camScale;
            ctx.globalAlpha = alpha;
            ctx.strokeStyle = "rgba(251,191,36,0.98)";
            ctx.lineWidth = Math.max(1.4, 1.8 * camScale);
            for (let rayIdx = 0; rayIdx < 8; rayIdx += 1) {{
              const angle = (Math.PI * 2 * rayIdx) / 8 - Math.PI / 2;
              const x1 = pt.x + Math.cos(angle) * rayInner;
              const y1 = pt.y + Math.sin(angle) * rayInner;
              const x2 = pt.x + Math.cos(angle) * rayOuter;
              const y2 = pt.y + Math.sin(angle) * rayOuter;
              ctx.beginPath();
              ctx.moveTo(x1, y1);
              ctx.lineTo(x2, y2);
              ctx.stroke();
            }}
            ctx.beginPath();
            ctx.fillStyle = "rgba(250,204,21,0.98)";
            ctx.arc(pt.x, pt.y, Math.max(1.2, r - 0.3 * camScale), 0, Math.PI * 2);
            ctx.fill();
            ctx.beginPath();
            ctx.strokeStyle = "rgba(255,255,255,0.92)";
            ctx.globalAlpha = Math.min(1, alpha * 0.95);
            ctx.lineWidth = Math.max(1.1, 1.5 * camScale);
            ctx.arc(pt.x, pt.y, Math.max(0.8, r - 0.55 * camScale), 0, Math.PI * 2);
            ctx.stroke();
          }} else if (foreignPerson) {{
            ctx.globalAlpha = alpha;
            drawForeignRect(
              pt,
              r,
              col,
              active ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.16)",
              Math.min(1, alpha * (active ? 0.80 : 0.62)),
              active ? (0.35 + p * 0.35) : 0
            );
          }} else {{
            ctx.beginPath();
            ctx.fillStyle = col;
            ctx.globalAlpha = alpha;
            ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
            ctx.fill();
            ctx.beginPath();
            ctx.strokeStyle = active ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.16)";
            ctx.globalAlpha = Math.min(1, alpha * (active ? 0.80 : 0.62));
            ctx.lineWidth = Math.max(0.9, 1.1 * camScale);
            ctx.arc(pt.x, pt.y, Math.max(0.6, r - 0.25 * camScale), 0, Math.PI * 2);
            ctx.stroke();
            if (active) {{
              ctx.beginPath();
              ctx.strokeStyle = "rgba(255,255,255,0.22)";
              ctx.globalAlpha = 0.35 + p * 0.35;
              ctx.lineWidth = 1 * camScale;
              ctx.arc(pt.x, pt.y, r + 2.6 * camScale, 0, Math.PI * 2);
              ctx.stroke();
            }}
          }}
        }}
        ctx.globalAlpha = 1.0;
        ctx.lineWidth = 1;

        if (hover || (selectedIdx >= 0 && selected)) {{
          const n = hover || selected;
          const pt = worldToScreen(n.x, n.y);
          if (isForeignPerson(n) && !isSpecialSunPerson(n)) {{
            const size = 10 * camScale;
            ctx.strokeStyle = "rgba(255,255,255,0.75)";
            ctx.lineWidth = 2 * camScale;
            ctx.strokeRect(pt.x - size, pt.y - size, size * 2, size * 2);
          }} else {{
            ctx.beginPath();
            ctx.strokeStyle = isSpecialSunPerson(n) ? "rgba(251,191,36,0.98)" : "rgba(255,255,255,0.75)";
            ctx.lineWidth = 2 * camScale;
            ctx.arc(pt.x, pt.y, isSpecialSunPerson(n) ? 13 * camScale : 10 * camScale, 0, Math.PI * 2);
            ctx.stroke();
          }}
        }}
      }};

      const reduceMotion = (() => {{
        try {{
          return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        }} catch (_) {{
          return false;
        }}
      }})();

      const animate = (nowMs) => {{
        if (reduceMotion) return;
        const t = (nowMs || 0) * 0.001;
        for (const n of nodes) {{
          const target = inWindow(n) ? 1 : 0;
          if (typeof n.p !== "number") n.p = target;
          n.p = n.p + (target - n.p) * 0.10;
          const seed = hash(n.person || "");
          const oy = Math.cos(t * 0.50 + (seed % 777) * 0.01) * 1.8 + Math.cos(t * 0.19 + (seed % 83)) * 0.8;
          const bx = n.bx != null ? n.bx : n.x;
          const by = n.by != null ? n.by : n.y;
          n.x = clamp(bx, pad, W - pad);
          n.y = clamp(by + oy, pad, H - pad);
        }}
        draw();
        window.requestAnimationFrame(animate);
      }};

      const pickNode = (mx, my) => {{
        const w = screenToWorld(mx, my);
        let best = null;
        let bestD = 999999;
        for (const n of nodes) {{
          const dx = w.x - n.x;
          const dy = w.y - n.y;
          const d = dx*dx + dy*dy;
          const thr = (16 / camScale);
          if (d < bestD && d < thr*thr) {{
            bestD = d;
            best = n;
          }}
        }}
        return best;
      }};

      const buildTooltipInnerHtml = (n) => {{
        const tipModel = buildPersonTooltipModel(n, {{ fallbackName: '相关人物' }});
        const rowHtml = tipModel.rows.map((row) => `<div class="text-white/70 text-[11px] mt-1">${{esc(row.label)}}：${{esc(row.value)}}</div>`).join("");
        const tline = tipModel.tagline ? `<div class="text-amber-200/95 text-[11px] mt-1 whitespace-pre-wrap">“${{esc(tipModel.tagline)}}”</div>` : "";
        const badge = !tipModel.hasStory ? ` <span class="ml-1 px-1.5 py-0.5 rounded-md bg-amber-400/30 text-amber-100 text-[10px] font-medium align-middle">${{esc(tipModel.badgeText)}}</span>` : "";
        return `<div class="font-bold text-white/95">${{esc(tipModel.name)}}${{badge}}</div>${{rowHtml}}${{tline}}`;
      }};
      const hideTooltipEl = (el) => {{
        if (el) el.classList.add("hidden");
      }};
      const placeTooltipEl = (el, hostRect, clientX, clientY) => {{
        if (!el || !hostRect) return;
        const safeClientX = Number.isFinite(Number(clientX)) ? Number(clientX) : (hostRect.left + hostRect.width / 2);
        const safeClientY = Number.isFinite(Number(clientY)) ? Number(clientY) : (hostRect.top + hostRect.height / 2);
        let left = safeClientX - hostRect.left + 10;
        let top = safeClientY - hostRect.top + 10;
        const tw = 260;
        const th = 146;
        if (left + tw > hostRect.width - 8) left = Math.max(8, safeClientX - hostRect.left - tw - 10);
        if (top + th > hostRect.height - 8) top = Math.max(8, safeClientY - hostRect.top - th - 10);
        el.style.left = left + "px";
        el.style.top = top + "px";
        el.classList.remove("hidden");
      }};
      const showTip = (n, clientX, clientY) => {{
        if (!n) {{
          hideTooltipEl($tip);
          setHoverMarkers(null);
          return;
        }}
        $tip.innerHTML = buildTooltipInnerHtml(n);
        placeTooltipEl($tip, $c.getBoundingClientRect(), clientX, clientY);
        setHoverMarkers(n);
      }};
      const showMapTip = (n, clientX, clientY) => {{
        if (!n || !$mapTip || !$chinaMap) {{
          hideTooltipEl($mapTip);
          return;
        }}
        $mapTip.innerHTML = buildTooltipInnerHtml(n);
        placeTooltipEl($mapTip, $chinaMap.getBoundingClientRect(), clientX, clientY);
      }};
      const closeMapTip = () => {{
        hideTooltipEl($mapTip);
      }};
      const resolveMapTipClientPoint = (evt, lng, lat) => {{
        const eventClientX = Number(evt && evt.originEvent ? evt.originEvent.clientX : evt && evt.clientX);
        const eventClientY = Number(evt && evt.originEvent ? evt.originEvent.clientY : evt && evt.clientY);
        if (Number.isFinite(eventClientX) && Number.isFinite(eventClientY)) {{
          return {{ clientX: eventClientX, clientY: eventClientY }};
        }}
        try {{
          if (amap && typeof amap.lngLatToContainer === "function" && $chinaMap) {{
            const pixel = amap.lngLatToContainer([lng, lat]);
            const px = Number(pixel && pixel.x);
            const py = Number(pixel && pixel.y);
            if (Number.isFinite(px) && Number.isFinite(py)) {{
              const rect = $chinaMap.getBoundingClientRect();
              return {{ clientX: rect.left + px, clientY: rect.top + py }};
            }}
          }}
        }} catch (_) {{}}
        const rect = $chinaMap ? $chinaMap.getBoundingClientRect() : {{ left: 0, top: 0, width: 0, height: 0 }};
        return {{
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
        }};
      }};

      const applyEdgeFilters = () => {{
        edgesAll = [];
        edges = [];
        neigh = [];
        edgeMeta = new Map();
        draw();
        if (currentTab === "map") {{
          updateMapMarkers();
        }}
      }};

      const PIXEL_STAGE_FLOW = [
        {{ key: "queued", label: "排队" }},
        {{ key: "search", label: "检索" }},
        {{ key: "map", label: "定位" }},
        {{ key: "draft", label: "成稿" }},
        {{ key: "review", label: "审阅" }},
        {{ key: "deliver", label: "交付" }},
      ];
      const PIXEL_AGENT_CARDS = [
        {{ key: "search", label: "Search", role: "检索史料" }},
        {{ key: "map", label: "Map", role: "校正地点" }},
        {{ key: "draft", label: "Editor", role: "组织成稿" }},
        {{ key: "review", label: "Critic", role: "审阅校验" }},
        {{ key: "deliver", label: "Deliver", role: "保存交付" }},
      ];
      const PIXEL_IDLE_STATES = [
        {{
          key: "idle",
          person: "橙子Agent",
          sceneTitle: "待命",
          stage: "待命",
          speech: "待命中",
          summary: "暂无任务，正在工位待命。",
          footer: "空闲中",
        }},
        {{
          key: "nap",
          person: "橙子Agent",
          sceneTitle: "小睡",
          stage: "打盹",
          speech: "打盹中",
          summary: "暂无任务，正在工位小睡。",
          footer: "空闲中",
        }},
        {{
          key: "stroll",
          person: "橙子Agent",
          sceneTitle: "巡查",
          stage: "遛弯",
          speech: "巡查中",
          summary: "暂无任务，正在附近巡查。",
          footer: "空闲中",
        }},
      ];
      let pixelGenCollapsed = true;
      let pixelGenPinnedExpanded = false;
      let pixelGenHovering = false;
      let pixelGenDetailExpanded = false;
      let pixelGenTypingSeq = 0;
      let pixelGenTypingTimer = null;
      let pixelIdleSceneTimer = null;
      let pixelGenState = {{
        visible: true,
        person: "橙子Agent",
        status: "idle",
        sceneTitle: "工位",
        idleStageLabel: "空闲中",
        summary: "暂无任务。",
        footerText: "空闲中",
        progress: [],
        stageKey: "queued",
        speechText: "",
        idleSceneKey: "idle",
      }};
      let currentGeneratePerson = "";
      let pendingPersonPageTab = null;
      let pendingPersonPageTabPerson = "";
      const runtimeReadinessEnabled = !STATIC_SITE || !!resolvedApiBase;
      const SEARCH_HINT_LINE_ONE_HTML = '<span class="home-search-hint-line"><strong>1. 内置人教版教材500+历史人物，可以直接访问</strong></span>';
      const SEARCH_HINT_LINE_TWO_HTML = '<span class="home-bili-highlight">2. 欢迎B站用户投币 投币 三连：<a href="https://www.bilibili.com/video/BV1u3LX66Eh7/" target="_blank" rel="noopener noreferrer">「我把2000年中国名人做成了动态地图，还能和李白聊天」</a></span>';
      const DEFAULT_SEARCH_HINT_HTML = SEARCH_HINT_LINE_ONE_HTML + SEARCH_HINT_LINE_TWO_HTML;
      const buildSearchHintHtml = (runtimeLine = "") => {{
        const runtime = String(runtimeLine || "").trim();
        return SEARCH_HINT_LINE_ONE_HTML + (runtime ? `<span class="home-search-hint-runtime">${{runtime}}</span>` : "") + SEARCH_HINT_LINE_TWO_HTML;
      }};
      let runtimeAvailability = {{
        checked: false,
        backendExpected: runtimeReadinessEnabled,
        backendAvailable: !runtimeReadinessEnabled,
        serveReady: !runtimeReadinessEnabled,
        generateReady: !runtimeReadinessEnabled,
        mode: runtimeReadinessEnabled ? "checking" : "browser_only",
        summary: runtimeReadinessEnabled ? "正在检查实时生成服务…" : requireBackend("实时人物分析"),
        queuePending: 0,
        queueLimit: 0,
        dependencySummary: runtimeReadinessEnabled ? "检查中" : "未接入后端",
        alerts: [],
      }};
      const renderOpsChip = (el, tone, value) => {{
        if (!el) return;
        const normalizedTone = String(tone || "muted").trim() || "muted";
        el.className = "pixel-progress-opschip is-" + normalizedTone;
        const valueEl = el.querySelector(".pixel-progress-opschip-value");
        if (valueEl) valueEl.textContent = String(value || "").trim() || "待命";
      }};
      const resolveRuntimeBlockMessage = () => {{
        if (runtimeAvailability.mode === "browser_only") return requireBackend("实时人物分析");
        if (runtimeAvailability.mode === "backend_unreachable") return "后端暂时不可达，当前仅支持浏览已生成人物页，请稍后再试。";
        if (runtimeAvailability.mode === "serve_unready") return "服务正在恢复，当前可稍后再试实时生成。";
        if (runtimeAvailability.mode === "generate_paused") return "实时生成人物暂时暂停，可先浏览已有内容，稍后再试。";
        return "";
      }};
      const syncRuntimeOpsBoard = () => {{
        const queueValue = runtimeAvailability.checked
          ? (runtimeAvailability.queueLimit > 0 ? `${{runtimeAvailability.queuePending}} / ${{runtimeAvailability.queueLimit}}` : String(runtimeAvailability.queuePending || 0))
          : "等待采样";
        renderOpsChip(
          $pixelGenOpsServe,
          runtimeAvailability.mode === "serve_unready" || runtimeAvailability.mode === "backend_unreachable" ? "error" : "success",
          runtimeAvailability.mode === "backend_unreachable" ? "后端离线" : (runtimeAvailability.serveReady ? "可浏览" : "恢复中"),
        );
        renderOpsChip(
          $pixelGenOpsGenerate,
          runtimeAvailability.generateReady ? "success" : (runtimeAvailability.mode === "generate_paused" ? "warning" : "error"),
          runtimeAvailability.generateReady ? "可生成" : (runtimeAvailability.mode === "browser_only" ? "需后端" : "已暂停"),
        );
        renderOpsChip(
          $pixelGenOpsQueue,
          runtimeAvailability.queuePending > 0 ? "warning" : "muted",
          queueValue,
        );
        renderOpsChip(
          $pixelGenOpsDeps,
          runtimeAvailability.generateReady ? "success" : (runtimeAvailability.checked ? "warning" : "muted"),
          runtimeAvailability.dependencySummary || "等待采样",
        );
      }};
      const pickPixelIdleState = (excludeKey = "") => {{
        const states = PIXEL_IDLE_STATES.filter((item) => item && item.key !== excludeKey);
        const pool = states.length ? states : PIXEL_IDLE_STATES;
        const idx = Math.floor(Math.random() * Math.max(1, pool.length));
        return pool[idx] || PIXEL_IDLE_STATES[0];
      }};
      const applyPixelIdleScene = (key) => {{
        const safeKey = String(key || "idle").trim() || "idle";
        if ($pixelOcelotWrap) $pixelOcelotWrap.dataset.idleScene = safeKey;
        if ($pixelGenScene) $pixelGenScene.dataset.idleScene = safeKey;
      }};
      const clearPixelIdleSceneRotation = () => {{
        if (pixelIdleSceneTimer) {{
          try {{ clearTimeout(pixelIdleSceneTimer); }} catch (_) {{}}
          pixelIdleSceneTimer = null;
        }}
      }};
      const schedulePixelIdleSceneRotation = () => {{
        clearPixelIdleSceneRotation();
        pixelIdleSceneTimer = window.setTimeout(() => {{
          if (String(pixelGenState.status || "").trim() !== "idle") return;
          const next = pickPixelIdleState(String(pixelGenState.idleSceneKey || ""));
          updatePixelProgressPanel({{
            status: "idle",
            idleSceneKey: next.key,
            person: next.person,
            sceneTitle: next.sceneTitle,
            idleStageLabel: next.stage,
            summary: next.summary,
            footerText: next.footer,
            speechText: next.speech,
          }});
        }}, 7000 + Math.floor(Math.random() * 5000));
      }};
      const resolvePixelStageKey = (status, lastTxt, lastDetail, progress) => {{
        const head = String(lastTxt || "").trim();
        const detail = String(lastDetail || "").trim();
        const tail = Array.isArray(progress) && progress.length ? String(progress[progress.length - 1].label || "").trim() : "";
        const text = `${{head}} ${{detail}} ${{tail}}`.toLowerCase();
        if (status === "idle") return "queued";
        if (status === "queued") return "queued";
        if (status === "completed" || status === "failed" || status === "partial_failed") return "deliver";
        if (text.includes("searchagent") || text.includes("检索") || text.includes("理解任务")) return "search";
        if (text.includes("mapagent") || text.includes("古今地名") || text.includes("坐标") || text.includes("解析地点")) return "map";
        if (text.includes("editoragent") || text.includes("首稿") || text.includes("markdown") || text.includes("生成人物档案")) return "draft";
        if (text.includes("criticagent") || text.includes("审阅") || text.includes("检查")) return "review";
        if (text.includes("保存") || text.includes("输出结论") || text.includes("构建时空结果") || text.includes("打开人物页") || text.includes("完成")) return "deliver";
        return "search";
      }};
      const resolvePixelStageLabel = (status, stageKey) => {{
        if (status === "idle") return String(pixelGenState.idleStageLabel || "").trim() || "空闲中";
        if (status === "queued") return "排队分发任务";
        if (status === "completed") return "交付完成";
        if (status === "failed") return "生成失败";
        if (status === "partial_failed") return "部分完成";
        if (stageKey === "search") return "检索人物资料";
        if (stageKey === "map") return "补齐地点坐标";
        if (stageKey === "draft") return "生成正文初稿";
        if (stageKey === "review") return "审阅与校验";
        if (stageKey === "deliver") return "保存并准备打开";
        return "等待开始";
      }};
      const resolvePixelLampClass = (status) => {{
        if (status === "idle") return "is-idle";
        if (status === "queued") return "is-queued";
        if (status === "failed" || status === "partial_failed") return "is-failed";
        if (status === "completed") return "is-completed";
        if (status === "running") return "is-running";
        return "";
      }};
      const resolvePixelBadgeClass = (status) => {{
        if (status === "idle") return "is-idle";
        if (status === "queued") return "is-queued";
        if (status === "failed" || status === "partial_failed") return "is-failed";
        if (status === "completed") return "is-completed";
        if (status === "running") return "is-running";
        return "is-idle";
      }};
      const renderPixelSceneLights = (status, stageKey) => {{
        if (!pixelGenSceneLights.length) return;
        const defs = [
          {{ on: status === "idle" || status === "queued", tint: status === "idle" ? "is-cyan" : "is-amber" }},
          {{ on: status === "running" || stageKey === "review", tint: "is-green" }},
          {{ on: stageKey === "deliver" || status === "completed", tint: "is-cyan" }},
        ];
        pixelGenSceneLights.forEach((el, idx) => {{
          const conf = defs[idx] || {{ on: false, tint: "" }};
          el.className = "pixel-progress-scene-light" + (conf.tint ? ` ${{conf.tint}}` : "") + (conf.on ? " is-on" : "");
        }});
      }};
      const setPixelPanelCollapsed = (collapsed) => {{
        pixelGenCollapsed = !!collapsed;
        if ($pixelGenBody) $pixelGenBody.style.display = pixelGenCollapsed ? "none" : "";
        if ($pixelGenPanel) $pixelGenPanel.classList.toggle("is-collapsed", pixelGenCollapsed);
        if ($pixelGenPanel) {{
          $pixelGenPanel.setAttribute("aria-label", `系统状态：${{resolvePixelCompactText(String(pixelGenState.status || "idle"), String(pixelGenState.stageKey || ""))}}`);
          $pixelGenPanel.setAttribute("title", "系统状态：只读展示，不能手动暂停或恢复");
        }}
        if ($pixelGenToggle) {{
          if (STAR_OFFICE_OPEN_IN_NEW_TAB) {{
            $pixelGenToggle.textContent = "↗";
            $pixelGenToggle.setAttribute("aria-expanded", "false");
            $pixelGenToggle.setAttribute("aria-label", "查看 Orange Office 详情（状态只读）");
            $pixelGenToggle.setAttribute("title", "查看 Orange Office 详情（状态只读，不能手动暂停或恢复）");
          }} else {{
            $pixelGenToggle.textContent = pixelGenCollapsed ? "+" : "-";
            $pixelGenToggle.setAttribute("aria-expanded", pixelGenCollapsed ? "false" : "true");
            $pixelGenToggle.setAttribute("aria-label", pixelGenCollapsed ? "展开看板" : "收起看板");
            $pixelGenToggle.setAttribute("title", pixelGenCollapsed ? "展开看板" : "收起看板");
          }}
        }}
      }};
      const setPixelPanelPinnedExpanded = (expanded) => {{
        pixelGenPinnedExpanded = !!expanded;
      }};
      const openStarOfficeInNewTab = () => {{
        try {{
          const nextTab = window.open(STAR_OFFICE_URL, "_blank", "noopener");
          if (nextTab) return;
        }} catch (_) {{}}
        try {{
          window.location.href = STAR_OFFICE_URL;
        }} catch (_) {{}}
      }};
      const shouldOpenStarOfficeFromPanelEvent = (target) => {{
        if (!STAR_OFFICE_OPEN_IN_NEW_TAB) return false;
        if (!$pixelGenPanel) return false;
        const node = target instanceof Element ? target : null;
        if (!node) return true;
        if ($pixelGenToggle && ($pixelGenToggle === node || $pixelGenToggle.contains(node))) return false;
        const interactive = node.closest("button, a, input, select, textarea, label, summary, iframe");
        if (!interactive) return true;
        return $pixelGenPanel === interactive;
      }};
      const openPixelPanelTemporarily = () => {{
        if (STAR_OFFICE_OPEN_IN_NEW_TAB) return;
        pixelGenHovering = true;
        if (!pixelGenPinnedExpanded && pixelGenCollapsed) setPixelPanelCollapsed(false);
      }};
      const maybeCollapsePixelPanel = () => {{
        if (STAR_OFFICE_OPEN_IN_NEW_TAB) return;
        pixelGenHovering = false;
        if (!pixelGenPinnedExpanded) setPixelPanelCollapsed(true);
      }};
      const setPixelSpeechText = (text) => {{
        if ($pixelGenSpeech) $pixelGenSpeech.textContent = String(text || "").trim() || "等待任务状态更新…";
      }};
      const resolvePixelSceneSpeech = (status) => {{
        if (status === "idle") return String(pixelGenState.speechText || runtimeAvailability.summary || "").trim() || "空闲中";
        if (status === "queued") return "排队中";
        if (status === "completed") return "已完成";
        if (status === "failed") return "执行失败";
        if (status === "partial_failed") return "部分完成";
        if (status === "running") return "执行中";
        return "等待任务状态更新…";
      }};
      const typePixelSpeech = (text) => {{
        const value = String(text || "").trim() || "等待任务状态更新…";
        pixelGenTypingSeq += 1;
        const seq = pixelGenTypingSeq;
        if (pixelGenTypingTimer) {{
          try {{ clearTimeout(pixelGenTypingTimer); }} catch (_) {{}}
          pixelGenTypingTimer = null;
        }}
        if (reduceMotion || value.length <= 18) {{
          setPixelSpeechText(value);
          return;
        }}
        const showChars = (count) => {{
          if (seq !== pixelGenTypingSeq) return;
          setPixelSpeechText(value.slice(0, count));
          if (count >= value.length) return;
          const nextCount = Math.min(value.length, count + (count < 20 ? 3 : 2));
          pixelGenTypingTimer = setTimeout(() => showChars(nextCount), 24);
        }};
        showChars(1);
      }};
      const setPixelDetailText = (text) => {{
        if (!$pixelGenDetail) return;
        const value = String(text || "").trim();
        const safe = value || "等待任务状态更新…";
        $pixelGenDetail.textContent = safe;
        const longText = safe.length > 54;
        $pixelGenDetail.classList.toggle("is-collapsed", longText && !pixelGenDetailExpanded);
        if ($pixelGenDetailHint) {{
          $pixelGenDetailHint.textContent = longText ? (pixelGenDetailExpanded ? "点击收起" : "点击展开") : "自动摘要";
        }}
      }};
      const renderPixelProgressSteps = (status, stageKey) => {{
        if (!$pixelGenSteps) return;
        const stageIdx = Math.max(0, PIXEL_STAGE_FLOW.findIndex((item) => item.key === stageKey));
        const isIdle = status === "idle";
        $pixelGenSteps.innerHTML = PIXEL_STAGE_FLOW.map((item, idx) => {{
          const done = !isIdle && (status === "completed" ? true : idx < stageIdx);
          const active = !isIdle && status !== "completed" && status !== "failed" && status !== "partial_failed" && idx === stageIdx;
          const cls = "pixel-progress-step" + (done ? " is-done" : "") + (active ? " is-active" : "");
          return `<div class="${{cls}}">${{item.label}}</div>`;
        }}).join("");
      }};
      const resolvePixelStatusText = (status) => {{
        if (status === "idle") {{
          if (runtimeAvailability.mode === "browser_only") return "只读";
          if (runtimeAvailability.mode === "backend_unreachable" || runtimeAvailability.mode === "serve_unready") return "恢复中";
          if (runtimeAvailability.mode === "generate_paused") return "降级";
          return "待命";
        }}
        if (status === "queued") return "排队";
        if (status === "running") return "执行中";
        if (status === "completed") return "已完成";
        if (status === "failed") return "失败";
        if (status === "partial_failed") return "部分完成";
        return String(status || "").trim() || "待命";
      }};
      const resolvePixelCompactText = (status, stageKey) => {{
        if (status === "running") return `进行中 · ${{resolvePixelStageLabel(status, stageKey)}}`;
        if (status === "queued") return "排队中";
        if (status === "completed") return "已生成";
        if (status === "failed" || status === "partial_failed") return "查看异常";
        if (runtimeAvailability.mode === "browser_only") return "系统 · 只读";
        if (runtimeAvailability.mode === "backend_unreachable") return "系统 · 离线";
        if (runtimeAvailability.mode === "serve_unready") return "系统 · 恢复中";
        if (runtimeAvailability.mode === "generate_paused") return "系统 · 生成暂停";
        return "系统 · 待命";
      }};
      const renderPixelAgentCards = (status, stageKey) => {{
        if (!$pixelGenAgents) return;
        const activeIdx = Math.max(0, PIXEL_AGENT_CARDS.findIndex((item) => item.key === stageKey || (stageKey === "queued" && item.key === "search")));
        const isIdle = status === "idle";
        $pixelGenAgents.innerHTML = PIXEL_AGENT_CARDS.map((item, idx) => {{
          const done = !isIdle && (status === "completed" ? true : idx < activeIdx);
          const active = !isIdle && status !== "completed" && status !== "failed" && status !== "partial_failed" && idx === activeIdx;
          const cls = "pixel-progress-agent" + (done ? " is-done" : "") + (active ? " is-active" : "");
          const stateText = isIdle ? "待命" : (active ? "处理中" : (done ? "已完成" : "等待"));
          return `<div class="${{cls}}"><div class="pixel-progress-agent-name">${{item.label}}</div><div class="pixel-progress-agent-role">${{item.role}}</div><div class="pixel-progress-agent-status">${{stateText}}</div></div>`;
        }}).join("");
      }};
      const escapePixelLogHtml = (value) => {{
        return String(value || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }};
      const renderPixelProgressLog = (status, progress) => {{
        if (!$pixelGenLog) return;
        const items = (Array.isArray(progress) ? progress : []).slice(-5);
        if (!items.length) {{
          $pixelGenLog.innerHTML = status === "idle"
            ? '<div class="pixel-progress-log-item"><div class="pixel-progress-log-label">空闲中</div><div class="pixel-progress-log-detail">输入人物后开始生成。</div></div>'
            : '<div class="pixel-progress-log-item"><div class="pixel-progress-log-label">等待中</div><div class="pixel-progress-log-detail">任务创建后会在这里持续显示最新执行步骤。</div></div>';
          return;
        }}
        $pixelGenLog.innerHTML = items.map((item) => {{
          const label = String((item && item.label) || "进度更新").trim() || "进度更新";
          const detail = String((item && item.detail) || "").trim();
          const time = String((item && item.time) || "").trim();
          const labelText = time ? `${{label}} · ${{time}}` : label;
          const safeLabelText = escapePixelLogHtml(labelText);
          const detailHtml = detail ? `<div class="pixel-progress-log-detail">${{escapePixelLogHtml(detail)}}</div>` : "";
          return `<div class="pixel-progress-log-item"><div class="pixel-progress-log-label">${{safeLabelText}}</div>${{detailHtml}}</div>`;
        }}).join("");
      }};
      const updatePixelProgressPanel = (patch = {{}}) => {{
        if (!$pixelGenPanel) return;
        const prevState = pixelGenState;
        pixelGenState = Object.assign({{}}, pixelGenState, patch || {{}});
        const person = String(pixelGenState.person || "").trim();
        const summary = String(pixelGenState.summary || "").trim();
        const progress = Array.isArray(pixelGenState.progress) ? pixelGenState.progress : [];
        const visible = pixelGenState.visible !== false;
        if (!visible) {{
          $pixelGenPanel.classList.add("hidden");
          return;
        }}
        const status = String(pixelGenState.status || "running").trim() || "running";
        const stageKey = String(pixelGenState.stageKey || "search").trim() || "search";
        if (!STAR_OFFICE_OPEN_IN_NEW_TAB && (status === "queued" || status === "running") && prevState && prevState.status === "idle" && pixelGenCollapsed) {{
          setPixelPanelPinnedExpanded(true);
          setPixelPanelCollapsed(false);
        }}
        if (!STAR_OFFICE_OPEN_IN_NEW_TAB && status === "idle" && prevState && prevState.status && prevState.status !== "idle" && !pixelGenHovering) {{
          setPixelPanelPinnedExpanded(false);
          setPixelPanelCollapsed(true);
        }}
        const stageIdx = Math.max(0, PIXEL_STAGE_FLOW.findIndex((item) => item.key === stageKey));
        const basePercent = status === "idle"
          ? 0
          : (status === "completed"
            ? 100
            : Math.round(((stageIdx + (status === "queued" ? 0 : 1)) / PIXEL_STAGE_FLOW.length) * 100));
        $pixelGenPanel.classList.remove("hidden");
        applyPixelIdleScene(String(pixelGenState.idleSceneKey || "idle"));
        if ($pixelGenPerson) $pixelGenPerson.textContent = person || "橙子Agent";
        if ($pixelGenSceneTitle) {{
          $pixelGenSceneTitle.textContent = status === "idle"
            ? (String(pixelGenState.sceneTitle || "").trim() || "工位")
            : "工位";
        }}
        if ($pixelGenStage) $pixelGenStage.textContent = resolvePixelStageLabel(status, stageKey);
        if ($pixelGenStatusText) $pixelGenStatusText.textContent = resolvePixelStatusText(status);
        if ($pixelGenLamp) $pixelGenLamp.className = "pixel-progress-lamp " + resolvePixelLampClass(status);
        if ($pixelGenStatusBadge) {{
          $pixelGenStatusBadge.className = "pixel-progress-badge " + resolvePixelBadgeClass(status);
          $pixelGenStatusBadge.textContent = resolvePixelStatusText(status);
        }}
        if ($pixelGenCompactText) {{
          $pixelGenCompactText.textContent = resolvePixelCompactText(status, stageKey);
        }}
        if ($pixelGenFooterText) {{
          $pixelGenFooterText.textContent = status === "idle"
            ? (String(pixelGenState.footerText || "").trim() || "空闲中")
            : (status === "queued"
            ? "任务已进入排队，等待分配算力"
            : (status === "completed"
              ? "产物已生成，正在准备打开页面"
              : (status === "failed" || status === "partial_failed"
                ? "任务已停止，请查看上方错误信息"
                : "橙子Agent 正在持续汇报 agent 的执行进度")));
        }}
        if ($pixelGenPercent) $pixelGenPercent.textContent = `${{basePercent}}%`;
        if ($pixelGenFill) $pixelGenFill.style.width = `${{basePercent}}%`;
        if (status === "idle") schedulePixelIdleSceneRotation();
        else clearPixelIdleSceneRotation();
        renderPixelSceneLights(status, stageKey);
        const sceneSpeech = resolvePixelSceneSpeech(status);
        setPixelDetailText(summary);
        if (sceneSpeech !== String(prevState?.speechText || "")) {{
          typePixelSpeech(sceneSpeech);
        }} else if (!$pixelGenSpeech || !String($pixelGenSpeech.textContent || "").trim()) {{
          setPixelSpeechText(sceneSpeech);
        }}
        pixelGenState.speechText = sceneSpeech;
        renderPixelProgressSteps(status, stageKey);
        renderPixelAgentCards(status, stageKey);
        renderPixelProgressLog(status, progress);
      }};
      try {{
        if ($pixelGenToggle) {{
          $pixelGenToggle.addEventListener("click", () => {{
            if (STAR_OFFICE_OPEN_IN_NEW_TAB) {{
              openStarOfficeInNewTab();
              return;
            }}
            if (pixelGenCollapsed) {{
              setPixelPanelPinnedExpanded(true);
              setPixelPanelCollapsed(false);
            }} else {{
              setPixelPanelPinnedExpanded(false);
              setPixelPanelCollapsed(true);
            }}
          }});
        }}
        if ($pixelGenPanel) {{
          $pixelGenPanel.addEventListener("mouseenter", openPixelPanelTemporarily);
          $pixelGenPanel.addEventListener("mouseleave", maybeCollapsePixelPanel);
          $pixelGenPanel.addEventListener("focusin", openPixelPanelTemporarily);
          $pixelGenPanel.addEventListener("focusout", () => {{
            try {{
              if ($pixelGenPanel.contains(document.activeElement)) return;
            }} catch (_) {{}}
            maybeCollapsePixelPanel();
          }});
        }}
        if ($pixelGenDetailCard) {{
          $pixelGenDetailCard.addEventListener("click", () => {{
            const safe = String(pixelGenState.summary || "").trim();
            if (safe.length <= 54) return;
            pixelGenDetailExpanded = !pixelGenDetailExpanded;
            setPixelDetailText(safe);
          }});
        }}
      }} catch (_) {{}}
      setPixelPanelCollapsed(true);
      const initialIdleState = pickPixelIdleState();
      pixelGenState = Object.assign({{}}, pixelGenState, {{
        idleSceneKey: initialIdleState.key,
        person: initialIdleState.person,
        sceneTitle: initialIdleState.sceneTitle,
        idleStageLabel: initialIdleState.stage,
        summary: initialIdleState.summary,
        footerText: initialIdleState.footer,
        speechText: initialIdleState.speech,
      }});
      updatePixelProgressPanel(pixelGenState);

      const setGenStatus = (txt) => {{
        const t = String(txt || "").trim();
        updatePixelProgressPanel({{
          visible: true,
          summary: t,
        }});
        if (!$genStatus) return;
        if (!t) {{
          $genStatus.classList.add("hidden");
          $genStatus.textContent = "";
          return;
        }}
        $genStatus.textContent = t;
        $genStatus.classList.remove("hidden");
      }};
      const clearGenerateRequestKey = (personName) => {{
        const person = String(personName || "").trim();
        if (!person) return;
        try {{
          const raw = sessionStorage.getItem("stellar_gen_idempotency_v1") || "";
          const payload = raw ? JSON.parse(raw) : {{}};
          if (!payload || typeof payload !== "object") return;
          delete payload[person];
          sessionStorage.setItem("stellar_gen_idempotency_v1", JSON.stringify(payload));
        }} catch (_) {{}}
      }};
      const isSafeGenerateRequestKey = (value) => /^[A-Za-z0-9._:-]+$/.test(String(value || "").trim());
      const getGenerateRequestKey = (personName) => {{
        const person = String(personName || "").trim();
        if (!person) return "";
        try {{
          const raw = sessionStorage.getItem("stellar_gen_idempotency_v1") || "";
          const payload = raw ? JSON.parse(raw) : {{}};
          const now = Date.now();
          const hit = payload && typeof payload === "object" ? payload[person] : null;
          if (hit && typeof hit === "object") {{
            const createdAt = Number(hit.created_at || 0);
            const key = String(hit.key || "").trim();
            if (key && isSafeGenerateRequestKey(key) && createdAt > 0 && (now - createdAt) < 10 * 60 * 1000) return key;
          }}
          const fresh = "storymap-" + now.toString(36) + "-" + Math.random().toString(36).slice(2, 10);
          const next = payload && typeof payload === "object" ? payload : {{}};
          next[person] = {{ key: fresh, created_at: now }};
          sessionStorage.setItem("stellar_gen_idempotency_v1", JSON.stringify(next));
          return fresh;
        }} catch (_) {{
          return "storymap-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
        }}
      }};
      const clearGenTask = () => {{
        clearTaskPoll();
        try {{ localStorage.removeItem("stellar_gen_task_v1"); }} catch (_) {{}}
        if (currentGeneratePerson) clearGenerateRequestKey(currentGeneratePerson);
        currentGeneratePerson = "";
        pendingPersonPageTab = null;
        pendingPersonPageTabPerson = "";
      }};
      const setGeneratingUI = (isGenerating) => {{
        const on = !!isGenerating;
        try {{
          if ($go) {{
            $go.dataset.loading = on ? "true" : "false";
            $go.setAttribute("aria-label", on ? "分析中" : "开始分析");
            $go.setAttribute("title", on ? "分析中" : "开始分析");
          }}
          if ($goLabel) $goLabel.textContent = on ? "分析中" : "开始分析";
        }} catch (_) {{}}
        try {{
          if (on) {{
            $go.classList.add("opacity-60");
            $go.classList.add("cursor-not-allowed");
          }} else {{
            $go.classList.remove("opacity-60");
            $go.classList.remove("cursor-not-allowed");
          }}
        }} catch (_) {{}}
        syncSearchActionState({{ generating: on }});
      }};
      const fetchWithTimeout = (url, ms, init) => {{
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), ms || 12000);
        return fetch(url, Object.assign({{ cache: "no-store", signal: controller.signal }}, init || {{}})).finally(() => clearTimeout(id));
      }};
      const normalizeRelativeHtmlFile = (file) => {{
        const raw = String(file || "").trim();
        if (!raw) return "";
        const cleaned = raw.split("#")[0].split("?")[0].replace(/\\/g, "/").replace(/^[.\/]+/, "");
        if (!cleaned) return "";
        const parts = cleaned.split("/").filter(Boolean);
        const leaf = parts.length ? parts[parts.length - 1] : "";
        return /\.html?$/i.test(leaf) ? leaf : "";
      }};
      const navigateToRelativeHtml = (file, options = {{}}) => {{
        const target = normalizeRelativeHtmlFile(file);
        if (!target) return false;
        const targetUrl = "./" + encodeURIComponent(target);
        const useNewTab = !!(options && options.newTab);
        if (useNewTab) {{
          try {{
            const link = document.createElement("a");
            link.href = targetUrl;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.style.display = "none";
            document.body.appendChild(link);
            link.click();
            link.remove();
            return true;
          }} catch (_) {{}}
        }}
        window.location.href = targetUrl;
        return true;
      }};
      const resolveStarOfficeUrl = (personName, taskId = "") => {{
        const params = new URLSearchParams();
        const person = String(personName || "").trim();
        const task = String(taskId || "").trim();
        if (person) params.set("person", person);
        if (task) params.set("task", task);
        const query = params.toString();
        return query ? (STAR_OFFICE_URL + "?" + query) : STAR_OFFICE_URL;
      }};
      const ensurePendingPersonTab = (personName) => {{
        const person = String(personName || "").trim();
        pendingPersonPageTabPerson = person;
        if (pendingPersonPageTab && !pendingPersonPageTab.closed) return pendingPersonPageTab;
        try {{
          const tab = window.open(resolveStarOfficeUrl(person), "_blank");
          if (!tab) return null;
          pendingPersonPageTab = tab;
          return tab;
        }} catch (_) {{
          return null;
        }}
      }};
      const navigatePendingPersonTabToOffice = (personName, taskId = "") => {{
        const person = String(personName || "").trim();
        if (!person) return false;
        if (pendingPersonPageTabPerson !== person) return false;
        const tab = pendingPersonPageTab;
        if (!tab || tab.closed) return false;
        try {{
          tab.location.href = resolveStarOfficeUrl(person, taskId);
          return true;
        }} catch (_) {{
          return false;
        }}
      }};
      const navigatePendingPersonTabToHtml = (personName, file) => {{
        const person = String(personName || "").trim();
        if (!person) return false;
        if (pendingPersonPageTabPerson !== person) return false;
        const tab = pendingPersonPageTab;
        if (!tab || tab.closed) return false;
        const target = normalizeRelativeHtmlFile(file);
        if (!target) return false;
        try {{
          tab.location.href = "./" + encodeURIComponent(target);
          pendingPersonPageTab = null;
          pendingPersonPageTabPerson = "";
          return true;
        }} catch (_) {{
          return false;
        }}
      }};
      const probeGeneratedPersonHtml = async (personName) => {{
        const person = String(personName || "").trim();
        if (!person) return "";
        const target = person + ".html";
        try {{
          const resp = await fetch("./" + encodeURIComponent(target), {{ method: "HEAD", cache: "no-store" }});
          if (resp && resp.ok) return target;
        }} catch (_) {{}}
        return "";
      }};
      const resolveTaskResultHtml = (result, fallbackPerson) => {{
        const files = Array.isArray(result && result.files) ? result.files : [];
        for (const item of files) {{
          const html = normalizeRelativeHtmlFile(item && item.html);
          if (html) return html;
        }}
        const multiHtml = normalizeRelativeHtmlFile(result && result.multi ? result.multi.html : "");
        if (multiHtml) return multiHtml;
        const people = Array.isArray(result && result.people) ? result.people : [];
        const preferredNames = [];
        const primaryName = String(people.length ? people[0] : (fallbackPerson || "")).trim();
        const fallbackName = String(fallbackPerson || "").trim();
        if (primaryName) preferredNames.push(primaryName);
        if (fallbackName && !preferredNames.includes(fallbackName)) preferredNames.push(fallbackName);
        for (const name of preferredNames) {{
          const found = nodes.find((n) => n && String(n.person || "").trim() === name) || null;
          const html = normalizeRelativeHtmlFile(found && found.file ? found.file : (name ? (name + ".html") : ""));
          if (html) return html;
        }}
        return "";
      }};
      let activeTaskPollId = "";
      let activeTaskPollGeneration = 0;
      let activeTaskPollTimer = 0;
      const clearTaskPoll = () => {{
        activeTaskPollId = "";
        activeTaskPollGeneration += 1;
        if (activeTaskPollTimer) {{
          clearTimeout(activeTaskPollTimer);
          activeTaskPollTimer = 0;
        }}
      }};
      const scheduleTaskPoll = (taskId, generation, tick, ms = 900) => {{
        if (activeTaskPollId !== taskId || generation !== activeTaskPollGeneration) return;
        if (activeTaskPollTimer) clearTimeout(activeTaskPollTimer);
        activeTaskPollTimer = setTimeout(() => {{
          activeTaskPollTimer = 0;
          if (activeTaskPollId !== taskId || generation !== activeTaskPollGeneration) return;
          tick();
        }}, ms);
      }};

      const openPerson = (name) => {{
        const q = String(name || "").trim();
        if (!q) return;
        const found = nodes.find((n) => n && String(n.person || "").trim() === q) || null;
        if (found && found.has_story === false) {{
          setGenStatus("「" + q + "」暂未收录人物页，正在尝试创建分析任务");
          ensurePendingPersonTab(q);
          ensurePersonGenerated(q);
          return;
        }}
        const file = found && found.file ? String(found.file) : "";
        if (navigateToRelativeHtml(file, {{ newTab: true }})) return;
        ensurePendingPersonTab(q);
        ensurePersonGenerated(q);
      }};
      window.__openPerson = openPerson;

      const pollTask = (taskId, personName) => {{
        const id = String(taskId || "").trim();
        if (!id) return;
        if (activeTaskPollId === id) return;
        clearTaskPoll();
        activeTaskPollId = id;
        activeTaskPollGeneration += 1;
        const generation = activeTaskPollGeneration;
        const person = String(personName || "").trim();
        currentGeneratePerson = person;
        let missingSnapshotCount = 0;
        let lastKnownProgress = [];
        let lastKnownSummary = "未找到本地人物「" + person + "」，正在创建分析任务，请稍候…";
        let lastKnownStageKey = "queued";
      let personPageOpened = false;
        const tick = async () => {{
          if (activeTaskPollId !== id || generation !== activeTaskPollGeneration) return;
          let snapshot = null;
          try {{
            const taskUrl = apiUrl("task?id=" + encodeURIComponent(id));
            const resp = await fetchWithTimeout(taskUrl, 12000);
            snapshot = await resp.json();
          }} catch (e) {{
            snapshot = null;
          }}
          if (!snapshot || snapshot.exists !== true) {{
            missingSnapshotCount += 1;
            const generatedHtml = await probeGeneratedPersonHtml(person);
            if (generatedHtml) {{
              const summary = "分析完成，正在打开人物页…";
              setGenStatus(summary);
              updatePixelProgressPanel({{
                visible: true,
                person,
                status: "completed",
                summary,
                progress: lastKnownProgress,
                stageKey: "deliver",
              }});
              setGeneratingUI(false);
              navigatePendingPersonTabToHtml(person, generatedHtml) || navigateToRelativeHtml(generatedHtml, {{ newTab: true }});
              clearGenTask();
              return;
            }}
            if (missingSnapshotCount <= 8) {{
              const summary = "任务状态同步中，请稍候…";
              setGenStatus(summary);
              updatePixelProgressPanel({{
                visible: true,
                person,
                status: "running",
                summary,
                progress: lastKnownProgress,
                stageKey: lastKnownStageKey,
              }});
              setGeneratingUI(true);
              scheduleTaskPoll(id, generation, tick, missingSnapshotCount >= 3 ? 1800 : 1100);
              return;
            }}
            const summary = lastKnownSummary ? (lastKnownSummary + "；任务状态同步失败，请稍后重试。") : "分析任务查询失败，请稍后重试";
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: "failed",
              summary,
              progress: lastKnownProgress,
              stageKey: "deliver",
            }});
            setGeneratingUI(false);
            clearGenTask();
            return;
          }}
          missingSnapshotCount = 0;
          const st = String(snapshot.status || "").trim();
          const queue = snapshot.queue || {{}};
          const pos = queue.position ? String(queue.position) : "";
          const active = queue.active_at_start ? String(queue.active_at_start) : (queue.active ? String(queue.active) : "");
          const limit = queue.limit ? String(queue.limit) : "";
          const progress = Array.isArray(snapshot.progress) ? snapshot.progress : [];
          const last = progress.length ? progress[progress.length - 1] : null;
          const lastTxt = last && last.label ? String(last.label) : "";
          const lastDetail = last && last.detail ? String(last.detail) : "";
          if (st === "queued") {{
            const qtxt = (pos && limit) ? ("排队中（" + pos + "/" + limit + "）") : "排队中";
            const summary = "未找到本地人物「" + person + "」，正在创建分析任务，请稍候… " + qtxt;
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: st,
              summary,
              progress,
              stageKey: "queued",
            }});
            setGeneratingUI(true);
            lastKnownProgress = progress;
            lastKnownSummary = summary;
            lastKnownStageKey = "queued";
            scheduleTaskPoll(id, generation, tick, 900);
            return;
          }}
          if (st === "running") {{
            const ptxt = lastDetail ? (lastTxt + "：" + lastDetail) : lastTxt;
            const head = "未找到本地人物「" + person + "」，正在分析并生成结果，请稍候…";
            const tail = ptxt ? ("（" + ptxt + "）") : (active && limit ? ("（执行中 " + active + "/" + limit + "）") : "");
            const summary = head + tail;
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: st,
              summary,
              progress,
              stageKey: resolvePixelStageKey(st, lastTxt, lastDetail, progress),
            }});
            setGeneratingUI(true);
            lastKnownProgress = progress;
            lastKnownSummary = summary;
            lastKnownStageKey = resolvePixelStageKey(st, lastTxt, lastDetail, progress);
            scheduleTaskPoll(id, generation, tick, 900);
            return;
          }}
          if (st === "failed") {{
            const summary = "分析失败：" + String(snapshot.error || "未知错误");
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: st,
              summary,
              progress,
              stageKey: "deliver",
            }});
            setGeneratingUI(false);
            clearGenTask();
            return;
          }}
          if (st === "partial_failed") {{
            const result = snapshot.result || {{}};
            const detail = String(snapshot.error || result.conclusion || "部分任务未成功");
            const summary = "分析部分完成：" + detail;
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: st,
              summary,
              progress,
              stageKey: "deliver",
            }});
            setGeneratingUI(false);
            clearGenTask();
            return;
          }}
          if (st === "completed") {{
            const result = snapshot.result || {{}};
            const ok = result && result.ok === true;
            const archive = result.archive || {{}};
            const archiveState = String(archive.state || "").trim();
            if (!ok) {{
              const summary = "分析失败：" + String(result.conclusion || snapshot.error || "未生成成功");
              setGenStatus(summary);
              updatePixelProgressPanel({{
                visible: true,
                person,
                status: "failed",
                summary,
                progress,
                stageKey: "deliver",
              }});
              setGeneratingUI(false);
              clearGenTask();
              return;
            }}
            const targetHtml = resolveTaskResultHtml(result, person);
            if (!targetHtml) {{
              setGenStatus("分析完成，但未找到可打开的人物页");
              setGeneratingUI(false);
              clearGenTask();
              return;
            }}
            if (!personPageOpened) {{
              personPageOpened = navigatePendingPersonTabToHtml(person, targetHtml) || navigateToRelativeHtml(targetHtml, {{ newTab: true }});
            }}
            if (!personPageOpened) {{
              setGenStatus("分析完成，但未找到可打开的人物页");
              setGeneratingUI(false);
              clearGenTask();
              return;
            }}
            if (archiveState === "queued" || archiveState === "running") {{
              const summary = "人物页已打开，群星首页与知识图谱正在后台补齐…";
              setGenStatus(summary);
              updatePixelProgressPanel({{
                visible: true,
                person,
                status: "running",
                summary,
                progress,
                stageKey: "deliver",
              }});
              setGeneratingUI(false);
              lastKnownProgress = progress;
              lastKnownSummary = summary;
              lastKnownStageKey = "deliver";
              scheduleTaskPoll(id, generation, tick, 1200);
              return;
            }}
            clearGenTask();
            const summary = archiveState === "completed"
              ? "人物页已打开，群星首页与知识图谱已补齐，正在刷新首页…"
              : "分析完成，人物页已打开";
            setGenStatus(summary);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: st,
              summary,
              progress,
              stageKey: "deliver",
            }});
            setGeneratingUI(false);
              clearGenTask();
            if (archiveState === "completed") {{
              setTimeout(() => {{
                try {{
                  window.location.reload();
                }} catch (_err) {{}}
              }}, 320);
            }}
            return;
          }}
          setGenStatus("分析任务状态异常，请稍后重试");
          setGeneratingUI(false);
          clearGenTask();
        }};
        tick();
      }};

      const ensurePersonGenerated = async (personName) => {{
        const person = String(personName || "").trim();
        if (!person) return;
        const blockedMessage = resolveRuntimeBlockMessage();
        if (blockedMessage) {{
          setGenStatus(blockedMessage);
          updatePixelProgressPanel({{
            visible: true,
            person,
            status: "idle",
            summary: blockedMessage,
            progress: [],
            stageKey: "queued",
          }});
          setGeneratingUI(false);
          return;
        }}
        try {{
          const existingHtml = await probeGeneratedPersonHtml(person);
          if (existingHtml) {{
            setGenStatus("");
            setGeneratingUI(false);
            navigateToRelativeHtml(existingHtml);
            return;
          }}
        }} catch (_) {{}}
        currentGeneratePerson = person;
        setGeneratingUI(true);
        setGenStatus("未找到本地人物「" + person + "」，正在创建分析任务，请稍候…");
        updatePixelProgressPanel({{
          visible: true,
          person,
          status: "queued",
          summary: "未找到本地人物「" + person + "」，正在创建分析任务，请稍候…",
          progress: [],
          stageKey: "queued",
        }});
        try {{
          const generateUrl = apiUrl("generate");
          const requestKey = getGenerateRequestKey(person);
          const resp = await fetchWithTimeout(generateUrl, 12000, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json", "X-Idempotency-Key": requestKey }},
            body: JSON.stringify({{ person }}),
          }});
          const data = await resp.json();
          if (!data || data.ok !== true || !data.task_id) {{
            const msg = data && data.error ? String(data.error) : "分析任务创建失败";
            const isPaused = msg === "service not ready for generate";
            setGenStatus(msg);
            updatePixelProgressPanel({{
              visible: true,
              person,
              status: isPaused ? "idle" : "failed",
              summary: msg,
              progress: [],
              stageKey: isPaused ? "queued" : "deliver",
            }});
            setGeneratingUI(false);
            return;
          }}
          const taskId = String(data.task_id || "").trim();
          try {{ localStorage.setItem("stellar_gen_task_v1", JSON.stringify({{ id: taskId, person }})); }} catch (_) {{}}
          navigatePendingPersonTabToOffice(person, taskId);
          pollTask(taskId, person);
        }} catch (e) {{
          setGenStatus("分析请求失败，请稍后重试");
          updatePixelProgressPanel({{
            visible: true,
            person,
            status: "failed",
            summary: "分析请求失败，请稍后重试",
            progress: [],
            stageKey: "deliver",
          }});
          setGeneratingUI(false);
          clearGenerateRequestKey(person);
          currentGeneratePerson = "";
        }}
      }};

      const resumeGenTask = () => {{
        let raw = "";
        try {{ raw = localStorage.getItem("stellar_gen_task_v1") || ""; }} catch (_) {{}}
        if (!raw) return;
        try {{
          const obj = JSON.parse(raw);
          const id = obj && obj.id ? String(obj.id) : "";
          const person = obj && obj.person ? String(obj.person) : "";
          if (id && person) {{
            pollTask(id, person);
            return;
          }}
        }} catch (_) {{}}
        clearGenTask();
        setGenStatus("");
      }};
      try {{
        document.addEventListener("visibilitychange", () => {{
          if (!document.hidden) resumeGenTask();
        }});
      }} catch (_) {{}}
      setTimeout(resumeGenTask, 300);

      const hideSearchSuggest = () => {{
        hideWorkTip();
        searchSuggestItems = [];
        searchSuggestActive = -1;
        if ($searchSuggest) {{
          $searchSuggest.classList.add("hidden");
          $searchSuggest.innerHTML = "";
        }}
      }};
      const syncIdleRuntimeStateToPanel = () => {{
        if (activeTaskPollId || currentGeneratePerson) return;
        if (String(pixelGenState.status || "").trim() !== "idle") return;
        const idleState = pickPixelIdleState(String(pixelGenState.idleSceneKey || ""));
        let idleStageLabel = idleState.stage;
        let summary = idleState.summary;
        let footerText = idleState.footer;
        let speechText = idleState.speech;
        if (runtimeAvailability.mode === "browser_only") {{
          idleStageLabel = "只读模式";
          summary = requireBackend("实时人物分析");
          footerText = "当前仅支持浏览已生成内容";
          speechText = "只读浏览";
        }} else if (runtimeAvailability.mode === "backend_unreachable") {{
          idleStageLabel = "等待恢复";
          summary = "后端暂时不可达，当前可继续浏览已有人物页。";
          footerText = "后端离线，暂不可生成";
          speechText = "等待恢复";
        }} else if (runtimeAvailability.mode === "serve_unready") {{
          idleStageLabel = "恢复中";
          summary = "服务正在恢复，浏览能力和生成能力将陆续恢复。";
          footerText = "服务恢复中";
          speechText = "恢复中";
        }} else if (runtimeAvailability.mode === "generate_paused") {{
          idleStageLabel = "降级运行";
          summary = "浏览能力正常，但实时生成人物已暂停，可稍后再试。";
          footerText = "可浏览，生成暂停";
          speechText = "生成暂停";
        }} else if (runtimeAvailability.mode === "active") {{
          summary = "服务在线，可以继续查询或发起实时人物生成。";
          footerText = "服务在线";
          speechText = "待命中";
        }}
        updatePixelProgressPanel({{
          visible: true,
          person: idleState.person,
          status: "idle",
          idleSceneKey: idleState.key,
          sceneTitle: idleState.sceneTitle,
          idleStageLabel,
          summary,
          footerText,
          speechText,
        }});
      }};
      const setSearchHint = () => {{
        if (!$searchHint) return;
        let runtimeLine = "";
        if (runtimeAvailability.mode === "browser_only") {{
          runtimeLine = '<span class="text-amber-200">当前为只读浏览模式，实时生成人物需要单独部署 FastAPI 后端。</span>';
        }} else if (runtimeAvailability.mode === "backend_unreachable") {{
          runtimeLine = '<span class="text-rose-200">当前后端不可达，仅建议浏览已有人物页；实时生成稍后再试。</span>';
        }} else if (runtimeAvailability.mode === "serve_unready") {{
          runtimeLine = '<span class="text-rose-200">服务正在恢复中，浏览与生成能力都可能受影响，请稍后重试。</span>';
        }} else if (runtimeAvailability.mode === "generate_paused") {{
          runtimeLine = '<span class="text-amber-200">当前可浏览但不可生成，系统正在等待 LLM / 地理编码依赖恢复。</span>';
        }} else if (runtimeAvailability.mode === "active") {{
          runtimeLine = '<span class="home-runtime-note">实时生成人物可用，若遇到排队或重试，橙子 Agent 会持续汇报进度。</span>';
        }} else if (runtimeAvailability.mode === "checking") {{
          runtimeLine = '<span class="text-sky-200">正在检查实时生成服务与依赖健康，请稍候…</span>';
        }}
        $searchHint.innerHTML = buildSearchHintHtml(runtimeLine);
      }};
      const refreshRuntimeAvailability = async () => {{
        if (!runtimeReadinessEnabled) {{
          setSearchHint();
          syncRuntimeOpsBoard();
          syncIdleRuntimeStateToPanel();
          return;
        }}
        try {{
          const response = await fetchWithTimeout(apiUrl("health/ready"), 8000, {{ cache: "no-store" }});
          const payload = await response.json();
          const queue = payload && payload.task && payload.task.queue ? payload.task.queue : {{}};
          const deps = payload && payload.dependency_status ? payload.dependency_status : {{}};
          const llmOk = !!(deps.llm && deps.llm.ok);
          const geocodeOk = !!(deps.geocode && deps.geocode.ok);
          runtimeAvailability = {{
            checked: true,
            backendExpected: true,
            backendAvailable: true,
            serveReady: !!(payload && payload.serve_ready),
            generateReady: !!(payload && payload.generate_ready),
            mode: !payload || payload.serve_ready === false ? "serve_unready" : (payload.generate_ready === false ? "generate_paused" : "active"),
            summary: !payload || payload.serve_ready === false
              ? "服务正在恢复中"
              : (payload.generate_ready === false ? "生成依赖暂未就绪" : "实时生成服务在线"),
            queuePending: Number(queue.pending || 0),
            queueLimit: Number(queue.limit || 0),
            dependencySummary: llmOk && geocodeOk ? "LLM / 地理编码正常" : (llmOk ? "地理编码待恢复" : (geocodeOk ? "LLM 待恢复" : "依赖待恢复")),
            alerts: Array.isArray(payload && payload.alerts) ? payload.alerts : [],
          }};
        }} catch (_) {{
          runtimeAvailability = {{
            checked: true,
            backendExpected: true,
            backendAvailable: false,
            serveReady: false,
            generateReady: false,
            mode: "backend_unreachable",
            summary: "后端暂时不可达",
            queuePending: 0,
            queueLimit: 0,
            dependencySummary: "后端离线",
            alerts: [],
          }};
        }}
        setSearchHint();
        syncRuntimeOpsBoard();
        syncIdleRuntimeStateToPanel();
      }};
      setSearchHint();
      syncRuntimeOpsBoard();
      syncIdleRuntimeStateToPanel();
      if (runtimeReadinessEnabled) {{
        setTimeout(() => {{
          refreshRuntimeAvailability();
          try {{
            window.setInterval(refreshRuntimeAvailability, 30000);
          }} catch (_) {{}}
        }}, 120);
      }}
      const scoreNodeMatch = (n, rawQuery) => {{
        const qRaw = String(rawQuery || "").trim();
        const q = normalizeSearchText(qRaw);
        if (!qRaw || !q) return null;
        const person = String(n.person || "").trim();
        const personNorm = normalizeSearchText(person);
        const aliases = uniqStrings(Array.isArray(n.aliases) ? n.aliases : []);
        const aliasNorms = aliases.map((x) => normalizeSearchText(x)).filter(Boolean);
        const foreignName = String(n.foreign_name || "").trim();
        const foreignNorm = normalizeSearchText(foreignName);
        const searchKeys = uniqStrings(Array.isArray(n.search_keys) ? n.search_keys : []);
        const searchTokens = uniqStrings(Array.isArray(n.search_tokens) ? n.search_tokens : []);
        const searchPinyin = uniqStrings(Array.isArray(n.search_pinyin) ? n.search_pinyin : []);

        if (person === qRaw) return {{ score: 1200, reason: "person_exact" }};
        if (personNorm === q) return {{ score: 1160, reason: "person_exact" }};
        if (aliases.some((x) => x === qRaw) || aliasNorms.includes(q)) return {{ score: 1120, reason: "alias_exact" }};
        if (foreignName && (foreignName === qRaw || foreignNorm === q)) return {{ score: 1090, reason: "foreign_exact" }};
        if (searchPinyin.includes(q)) return {{ score: 1060, reason: "pinyin_exact" }};

        if (personNorm && personNorm.startsWith(q)) return {{ score: 980, reason: "person_prefix" }};
        if (aliasNorms.some((x) => x.startsWith(q))) return {{ score: 950, reason: "alias_prefix" }};
        if (foreignNorm && foreignNorm.startsWith(q)) return {{ score: 930, reason: "foreign_prefix" }};
        if (searchPinyin.some((x) => x.startsWith(q))) return {{ score: 900, reason: "pinyin_prefix" }};

        if (q.length >= 2) {{
          if (personNorm && personNorm.includes(q)) return {{ score: 860, reason: "person_fuzzy" }};
          if (aliasNorms.some((x) => x.includes(q))) return {{ score: 830, reason: "alias_fuzzy" }};
          if (foreignNorm && foreignNorm.includes(q)) return {{ score: 810, reason: "foreign_fuzzy" }};
          if (searchTokens.some((x) => x.includes(q))) return {{ score: 760, reason: "token_fuzzy" }};
          if (searchKeys.some((x) => normalizeSearchText(x).includes(q))) return {{ score: 740, reason: "token_fuzzy" }};
        }}
        return null;
      }};
      const findPersonMatches = (query, limit = 8) => {{
        const qRaw = String(query || "").trim();
        const q = normalizeSearchText(qRaw);
        if (!qRaw || !q) return [];
        const matches = [];
        for (const n of nodes) {{
          const scored = scoreNodeMatch(n, qRaw);
          if (!scored) continue;
          matches.push({{ node: n, score: scored.score, reason: scored.reason }});
        }}
        matches.sort((a, b) => {{
          if (b.score !== a.score) return b.score - a.score;
          const ah = a.node && a.node.has_story === false ? 0 : 1;
          const bh = b.node && b.node.has_story === false ? 0 : 1;
          if (bh !== ah) return bh - ah;
          const ay = Number(a.node?.time_year ?? a.node?.birth_year ?? 0);
          const by = Number(b.node?.time_year ?? b.node?.birth_year ?? 0);
          if (by !== ay) return by - ay;
          return String(a.node?.person || "").localeCompare(String(b.node?.person || ""), "zh-Hans-CN");
        }});
        return matches.slice(0, Math.max(1, limit | 0));
      }};
      const renderSearchSuggest = (query) => {{
        if (!$searchSuggest) return;
        const matches = findPersonMatches(query, 8);
        searchSuggestItems = matches;
        searchSuggestActive = matches.length ? 0 : -1;
        if (!matches.length) {{
          hideSearchSuggest();
          return;
        }}
        $searchSuggest.innerHTML = matches.map((item, idx) => {{
          const n = item.node || {{}};
          const person = esc(String(n.person || ""));
          const reason = esc(searchSummaryLabel(item.reason));
          const years = esc(formatYearRange(n.birth_year, n.death_year));
          const aliasText = uniqStrings(Array.isArray(n.aliases) ? n.aliases : []).slice(0, 2).join(" / ");
          const foreignText = String(n.foreign_name || "").trim();
          const meta = [aliasText, foreignText].filter(Boolean).join(" · ");
          const metaLine = meta ? `<div class="text-[11px] text-slate-500 mt-0.5 truncate">${{esc(meta)}}</div>` : "";
          const works = uniqStrings(Array.isArray(n.works) ? n.works : [])
            .filter((work) => hasWorkSummaryContent(resolveNodeWorkSummary(n, work)))
            .slice(0, 3);
          const worksHtml = works.length
            ? `<div class="mt-2 flex flex-wrap gap-1.5">${{works.map((work) => `<span class="home-work-chip" data-search-idx="${{idx}}" data-work-title="${{esc(normalizeHomeWorkTitle(work))}}">《${{esc(normalizeHomeWorkTitle(work))}}》</span>`).join("")}}</div>`
            : "";
          const badge = n.has_story === false
            ? '<span class="ml-2 px-1.5 py-0.5 rounded-md bg-amber-100 text-amber-700 text-[10px] font-medium">暂未生成</span>'
            : "";
          const activeCls = idx === searchSuggestActive ? "bg-slate-50" : "bg-white";
          return (
            `<button type="button" data-search-idx="${{idx}}" class="w-full text-left px-4 py-3 border-b border-slate-100 last:border-b-0 hover:bg-slate-50 ${{activeCls}}">` +
              `<div class="flex items-center justify-between gap-3">` +
                `<div class="min-w-0">` +
                  `<div class="text-sm font-semibold text-slate-800 truncate">${{person}}${{badge}}</div>` +
                  `<div class="text-[11px] text-slate-400 mt-0.5">${{years}}</div>` +
                  `${{metaLine}}` +
                  `${{worksHtml}}` +
                `</div>` +
                `<div class="shrink-0 text-[11px] text-slate-400">${{reason}}</div>` +
              `</div>` +
            `</button>`
          );
        }}).join("");
        $searchSuggest.classList.remove("hidden");
      }};
      const pickSearchMatch = (fallbackName) => {{
        if (!searchSuggestItems.length) {{
          const list = findPersonMatches(fallbackName, 1);
          return list.length ? list[0] : null;
        }}
        if (searchSuggestActive >= 0 && searchSuggestActive < searchSuggestItems.length) return searchSuggestItems[searchSuggestActive];
        return searchSuggestItems[0] || null;
      }};
      const findPersonNode = (name) => {{
        const picked = pickSearchMatch(name);
        return picked ? picked.node : null;
      }};
      const focusKnownPerson = (name) => {{
        const n = findPersonNode(name);
        if (!n) return false;
        setSelected(n);
        if (currentTab === "map") {{
          setTab("map");
          setTimeout(() => {{
            const ok = centerMapOnPerson(n);
            pendingMapFocusPerson = ok ? "" : String(n.person || "").trim();
          }}, 260);
        }} else {{
          setTab("graph");
        }}
        return true;
      }};

      const onSearch = (ev) => {{
        const validation = validatePersonInput($q ? $q.value : "");
        if (!validation.ok) {{
          setSearchValidation(validation.reason);
          syncSearchActionState({{ showReason: true }});
          return;
        }}
        const rawName = validation.value;
        if ($q && rawName) $q.value = rawName;
        const picked = pickSearchMatch(rawName);
        const name = picked && picked.node ? String(picked.node.person || "").trim() : rawName;
        if (name) $q.value = name;
        hideSearchSuggest();
        if (focusKnownPerson(name)) return;
        const shouldGenerate = window.confirm(`该人物未收录，是否仍要尝试生成「${{rawName}}」？`);
        if (!shouldGenerate) return;
        openPerson(name || rawName);
      }};

      $go.addEventListener("click", (ev) => onSearch(ev));
      $q.addEventListener("input", () => {{
        syncSearchActionState();
        renderSearchSuggest($q.value);
      }});
      $q.addEventListener("focus", () => {{
        syncSearchActionState();
        renderSearchSuggest($q.value);
      }});
      $q.addEventListener("keydown", (e) => {{
        if (e.key === "ArrowDown") {{
          if (!searchSuggestItems.length) {{
            renderSearchSuggest($q.value);
          }} else {{
            searchSuggestActive = (searchSuggestActive + 1 + searchSuggestItems.length) % searchSuggestItems.length;
            renderSearchSuggest($q.value);
          }}
          e.preventDefault();
          return;
        }}
        if (e.key === "ArrowUp") {{
          if (searchSuggestItems.length) {{
            searchSuggestActive = (searchSuggestActive - 1 + searchSuggestItems.length) % searchSuggestItems.length;
            renderSearchSuggest($q.value);
          }}
          e.preventDefault();
          return;
        }}
        if (e.key === "Escape") {{
          hideSearchSuggest();
          return;
        }}
        if (e.key === "Enter") {{
          onSearch(e);
        }}
      }});
      if ($searchSuggest) {{
        $searchSuggest.addEventListener("mousedown", (e) => e.preventDefault());
        const syncSearchSuggestWorkTip = (e) => {{
          const chip = e && e.target && e.target.closest ? e.target.closest("[data-work-title][data-search-idx]") : null;
          if (!chip || !$searchSuggest.contains(chip)) {{
            hideWorkTip();
            return;
          }}
          const idx = Number(chip.getAttribute("data-search-idx"));
          const workTitle = normalizeHomeWorkTitle(chip.getAttribute("data-work-title") || "");
          if (!Number.isFinite(idx) || idx < 0 || idx >= searchSuggestItems.length || !workTitle) {{
            hideWorkTip();
            return;
          }}
          const item = searchSuggestItems[idx] && searchSuggestItems[idx].node
            ? resolveNodeWorkSummary(searchSuggestItems[idx].node, workTitle)
            : null;
          if (!item) {{
            hideWorkTip();
            return;
          }}
          showWorkTip(workTitle, item, e.clientX, e.clientY);
        }};
        $searchSuggest.addEventListener("mouseover", syncSearchSuggestWorkTip);
        $searchSuggest.addEventListener("mousemove", syncSearchSuggestWorkTip);
        $searchSuggest.addEventListener("mouseleave", () => hideWorkTip());
        $searchSuggest.addEventListener("click", (e) => {{
          const btn = e.target && e.target.closest ? e.target.closest("[data-search-idx]") : null;
          if (!btn) return;
          const idx = Number(btn.getAttribute("data-search-idx"));
          if (!Number.isFinite(idx) || idx < 0 || idx >= searchSuggestItems.length) return;
          searchSuggestActive = idx;
          const picked = searchSuggestItems[idx];
          const person = picked && picked.node ? String(picked.node.person || "").trim() : "";
          if (person) {{
            $q.value = person;
            onSearch(e);
          }}
        }});
      }}
      try {{
        document.addEventListener("click", (e) => {{
          const t = e.target;
          if (t === $q || t === $go) return;
          if ($searchSuggest && t && $searchSuggest.contains(t)) return;
          hideSearchSuggest();
        }});
      }} catch (_) {{}}
      try {{
        window.addEventListener("resize", () => hideWorkTip());
        document.addEventListener("scroll", () => hideWorkTip(), true);
      }} catch (_) {{}}

      let currentTab = "graph";
      let mapInited = false;
      let markers = [];
      let amap = null;
      let amapLoading = false;
      let coordFillRunning = false;
      let coordFillAddMarker = null;
      let pendingMapFocusPerson = "";
      let clusterer = null;
      let mapCameraTouched = false;
      const onlyActiveMarkers = true;
      let _fitMapTimer = null;
      let _persistTimer = null;
      let mapStyleValue = "amap://styles/macaron";
      let markerStyleValue = "circle";
      let searchCapabilities = {{ aliases: true, foreign_name: true, pinyin: false }};
      let searchSuggestItems = [];
      let searchSuggestActive = -1;

      const _setMapStyleValue = (style) => {{
        const s = String(style || "").trim();
        mapStyleValue = s === "amap://styles/macaron" ? "amap://styles/macaron" : "amap://styles/macaron";
        if ($mapStyle) {{
          try {{ $mapStyle.value = mapStyleValue; }} catch (_) {{}}
        }}
        try {{ localStorage.setItem("stellar_map_style_v1", mapStyleValue); }} catch (_) {{}}
        if (amap && typeof amap.setMapStyle === "function") {{
          try {{ amap.setMapStyle(mapStyleValue); }} catch (_) {{}}
        }}
      }};

      const _initMapStyleValue = () => {{
        let saved = "";
        try {{ saved = (localStorage.getItem("stellar_map_style_v1") || "").trim(); }} catch (_) {{}}
        if (saved === "amap://styles/macaron") mapStyleValue = "amap://styles/macaron";
        if ($mapStyle) {{
          try {{
            $mapStyle.value = "amap://styles/macaron";
            mapStyleValue = "amap://styles/macaron";
          }} catch (_) {{}}
          $mapStyle.addEventListener("change", () => _setMapStyleValue($mapStyle.value));
        }}
      }};
      _initMapStyleValue();

      const _getAmapKey = () => {{
        let k = "";
        try {{
          k = (new URLSearchParams(window.location.search).get("amapKey") || "").trim();
        }} catch (_) {{}}
        if (!k) k = (window.AMAP_KEY || localStorage.getItem("AMAP_KEY") || "").trim();
        return k;
      }};
      const _getAmapSecurity = () => {{
        let s = "";
        try {{
          s = (new URLSearchParams(window.location.search).get("amapSec") || "").trim();
        }} catch (_) {{}}
        if (!s) s = (window.AMAP_SECURITY || localStorage.getItem("AMAP_SECURITY") || "").trim();
        return s;
      }};
      const _ensureAmap = () => new Promise((resolve, reject) => {{
        if (window.AMap && typeof window.AMap.Map === "function") return resolve(true);
        const key = _getAmapKey();
        if (!key) return reject(new Error("AMAP_KEY_REQUIRED"));
        const sec = _getAmapSecurity();
        if (sec) {{
          window._AMapSecurityConfig = {{ securityJsCode: sec }};
        }}
        if (amapLoading) {{
          const t0 = Date.now();
          const tick = () => {{
            if (window.AMap && typeof window.AMap.Map === "function") return resolve(true);
            if (Date.now() - t0 > 12000) return reject(new Error("AMAP_LOAD_TIMEOUT"));
            setTimeout(tick, 80);
          }};
          return tick();
        }}
        amapLoading = true;
        const sEl = document.createElement("script");
        sEl.async = true;
        // Load AMap JS with geocoder plugin only; markers remain individual so color + hover stay stable.
        sEl.src = `https://webapi.amap.com/maps?v=2.0&key=${{encodeURIComponent(key)}}&plugin=AMap.Geocoder`;
        sEl.onload = () => {{
          amapLoading = false;
          if (window.AMap && typeof window.AMap.Map === "function") resolve(true);
          else reject(new Error("AMAP_LOAD_FAILED"));
        }};
        sEl.onerror = () => {{
          amapLoading = false;
          reject(new Error("AMAP_LOAD_FAILED"));
        }};
        document.head.appendChild(sEl);
      }});

      const COORD_CACHE_KEY = "stellar_birth_coords_wgs84_v1";
      const COORD_CACHE_OLD_KEY = "stellar_birth_coords_v1";
      const migrateCoordCache = () => {{
        try {{
          const oldRaw = localStorage.getItem(COORD_CACHE_OLD_KEY);
          if (!oldRaw) return;
          const oldObj = JSON.parse(oldRaw);
          if (!oldObj || typeof oldObj !== "object") return;
          const out = {{}};
          for (const k of Object.keys(oldObj)) {{
            const v = oldObj[k];
            if (!Array.isArray(v) || v.length < 2) continue;
            const latG = Number(v[0]);
            const lngG = Number(v[1]);
            if (!Number.isFinite(latG) || !Number.isFinite(lngG)) continue;
            const w = gcj02ToWgs84(latG, lngG);
            out[k] = [w.lat, w.lng];
          }}
          localStorage.setItem(COORD_CACHE_KEY, JSON.stringify(out));
          localStorage.removeItem(COORD_CACHE_OLD_KEY);
        }} catch (_) {{}}
      }};
      const readCoordCache = () => {{
        try {{
          const raw = localStorage.getItem(COORD_CACHE_KEY);
          const obj = raw ? JSON.parse(raw) : null;
          return (obj && typeof obj === "object") ? obj : {{}};
        }} catch (_) {{
          return {{}};
        }}
      }};
      const writeCoordCache = (cache) => {{
        try {{
          localStorage.setItem(COORD_CACHE_KEY, JSON.stringify(cache));
        }} catch (_) {{}}
      }};
      let _coordDirty = {{}};
      let _coordDirtyCount = 0;
      let _coordFlushTimer = null;
      const _flushCoordsToServer = () => {{
        const items = _coordDirty;
        const n = _coordDirtyCount;
        _coordDirty = {{}};
        _coordDirtyCount = 0;
        if (_coordFlushTimer) {{
          clearTimeout(_coordFlushTimer);
          _coordFlushTimer = null;
        }}
        if (!n) return;
        if (STATIC_SITE && !API_BASE) return;
        try {{
          fetch(apiUrl("coords/bulk"), {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ items }}),
          }}).catch(() => {{}});
        }} catch (_) {{}}
      }};
      const _markCoordDirty = (person, lat, lng) => {{
        const p = String(person || "").trim();
        if (!p) return;
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        _coordDirty[p] = [lat, lng];
        _coordDirtyCount += 1;
        if (_coordFlushTimer) return;
        _coordFlushTimer = setTimeout(_flushCoordsToServer, 1200);
      }};
      const applyCoordCacheToNodes = (cache) => {{
        if (!cache) return;
        for (const n of nodes) {{
          const k = String(n.person || "").trim();
          const v = k ? cache[k] : null;
          const has = (typeof n.birth_lat_wgs84 === "number" && typeof n.birth_lng_wgs84 === "number") || (typeof n.birth_lat === "number" && typeof n.birth_lng === "number");
          if (v && !has && Array.isArray(v) && v.length >= 2) {{
            const lat = Number(v[0]);
            const lng = Number(v[1]);
            if (Number.isFinite(lat) && Number.isFinite(lng)) {{
              n.birth_lat_wgs84 = lat;
              n.birth_lng_wgs84 = lng;
              n.birth_lat = lat;
              n.birth_lng = lng;
            }}
          }}
        }}
      }};

      const LEGACY_TIME_WINDOW_KEY = "stellar_time_window_v2";
      const LAST_MANUAL_TIME_WINDOW_KEY = "stellar_last_manual_time_window_v1";
      const clearLegacyTimeWindow = () => {{
        try {{
          localStorage.removeItem(LEGACY_TIME_WINDOW_KEY);
        }} catch (_) {{}}
      }};
      const persistTimeWindow = () => {{
        if (_persistTimer) clearTimeout(_persistTimer);
        _persistTimer = setTimeout(() => {{
          try {{
            localStorage.setItem(LAST_MANUAL_TIME_WINDOW_KEY, JSON.stringify({{
              a: startYear,
              b: endYear,
              sig: timeWindowSignature,
              saved_at: Date.now(),
            }}));
          }} catch (_) {{}}
        }}, 260);
      }};

      const scheduleMapFit = (force = false) => {{
        if (_fitMapTimer) clearTimeout(_fitMapTimer);
        _fitMapTimer = setTimeout(() => {{
          if (currentTab !== "map" || !mapInited || !amap) return;
          if (mapCameraTouched && !force) return;
          try {{
            const markersForFit = markers
              .map((item) => item && item.mk)
              .filter((item) => item && typeof item.getPosition === "function");
            if (!markersForFit.length) return;
            amap.setFitView(markersForFit, false, [56, 56, 56, 56], 4);
          }} catch (_) {{}}
        }}, 220);
      }};

      const centerMapOnPerson = (n) => {{
        if (!n || !amap) return false;
        const latW = (typeof n.birth_lat_wgs84 === "number") ? n.birth_lat_wgs84 : n.birth_lat;
        const lngW = (typeof n.birth_lng_wgs84 === "number") ? n.birth_lng_wgs84 : n.birth_lng;
        const p = wgs84ToGcj02(latW, lngW);
        const lat = p.lat;
        const lng = p.lng;
        if (typeof lat !== "number" || typeof lng !== "number") return false;
        try {{
          const z = Math.max(6, Number(amap.getZoom ? amap.getZoom() : 6) || 6);
          amap.setZoomAndCenter(Math.min(10, z), [lng, lat]);
          return true;
        }} catch (_) {{}}
        return false;
      }};
      const geocodeText = (n) => {{
        const m = String(n.birthplace_modern || "").trim().replace(/^今\s*/g, "");
        if (m) return m;
        const raw = String(n.birthplace_raw || "").trim();
        if (raw) {{
          const t = raw.split(/[；;，,]/)[0].replace(/[（(].*?[）)]/g, "").replace(/^约\s*/g, "").replace(/^公元前?\d+年\s*/g, "").trim();
          if (t) return t;
        }}
        const bp = String(n.birthplace || "").trim();
        return bp.split(/[；;，,]/)[0].replace(/[（(].*?[）)]/g, "").trim();
      }};
      const runSharedCoordFill = (cache, addMarkerIfReady) => {{
        if (addMarkerIfReady) coordFillAddMarker = addMarkerIfReady;
        if (coordFillRunning) return;
        const key = _getAmapKey();
        if (!key) return;
        coordFillRunning = true;
        applyCoordCacheToNodes(cache);
        updateCoordCount();
        _ensureAmap().then(() => {{
          if (!window.AMap || !window.AMap.Geocoder) {{
            coordFillRunning = false;
            return;
          }}
          const geocoder = new window.AMap.Geocoder({{ city: "全国" }});
          let idx = 0;
          const tick = () => {{
            while (idx < nodes.length) {{
              const n = nodes[idx++];
              if (!n) continue;
              if (typeof n.birth_lat_wgs84 === "number" && typeof n.birth_lng_wgs84 === "number") {{
                if (coordFillAddMarker && mapInited && amap) coordFillAddMarker(n);
                continue;
              }}
              const q = geocodeText(n);
              const person = String(n.person || "").trim();
              if (!q || !person) continue;
              geocoder.getLocation(q, (status, result) => {{
                if (status === "complete" && result && result.geocodes && result.geocodes.length) {{
                  const loc = result.geocodes[0].location;
                  if (loc && typeof loc.getLng === "function" && typeof loc.getLat === "function") {{
                    const lng = Number(loc.getLng());
                    const lat = Number(loc.getLat());
                    if (Number.isFinite(lat) && Number.isFinite(lng)) {{
                      const w = gcj02ToWgs84(lat, lng);
                      n.birth_lat_wgs84 = w.lat;
                      n.birth_lng_wgs84 = w.lng;
                      n.birth_lat = w.lat;
                      n.birth_lng = w.lng;
                      cache[person] = [w.lat, w.lng];
                      writeCoordCache(cache);
                      updateCoordCount();
                      _markCoordDirty(person, w.lat, w.lng);
                      if (coordFillAddMarker && mapInited && amap) {{
                        coordFillAddMarker(n);
                        updateMapMarkers();
                      }}
                      if (
                        pendingMapFocusPerson &&
                        currentTab === "map" &&
                        person === pendingMapFocusPerson &&
                        centerMapOnPerson(n)
                      ) {{
                        pendingMapFocusPerson = "";
                      }}
                    }}
                  }}
                }}
                if (idx >= nodes.length) {{
                  coordFillRunning = false;
                  _flushCoordsToServer();
                  return;
                }}
                setTimeout(tick, 140);
              }});
              return;
            }}
            coordFillRunning = false;
            writeCoordCache(cache);
            updateCoordCount();
            _flushCoordsToServer();
          }};
          setTimeout(tick, 400);
        }}).catch(() => {{
          coordFillRunning = false;
        }});
      }};
      const prefillCoordsNoMap = () => {{
        const cache = readCoordCache();
        applyCoordCacheToNodes(cache);
        updateCoordCount();
        runSharedCoordFill(cache, null);
      }};

      const refreshVisibleMapViewport = () => {{
        if (!mapInited || !amap || currentTab !== "map") return;
        setTimeout(() => {{
          if (!mapInited || !amap || currentTab !== "map") return;
          try {{
            if (typeof amap.resize === "function") amap.resize();
          }} catch (_) {{}}
          try {{
            updateMapMarkers();
          }} catch (_) {{}}
          if (mapSearchQuery) {{
            try {{
              focusMapOnSearchMatch();
            }} catch (_) {{}}
          }}
        }}, 32);
      }};
      const setTab = (tab) => {{
        currentTab = tab;
        if ($graphPane) {{
          if (tab === "graph") $graphPane.classList.remove("hidden");
          else $graphPane.classList.add("hidden");
        }}
        if ($mapPane) {{
          if (tab === "map") $mapPane.classList.remove("hidden");
          else $mapPane.classList.add("hidden");
        }}
        if ($tabGraph && $tabMap) {{
          if (tab === "graph") {{
            $tabGraph.className = "px-3 py-1 rounded-lg bg-white/15 border border-white/20 text-white/90";
            $tabMap.className = "px-3 py-1 rounded-lg bg-white/5 border border-white/10 text-white/70 hover:bg-white/10";
          }} else {{
            $tabGraph.className = "px-3 py-1 rounded-lg bg-white/5 border border-white/10 text-white/70 hover:bg-white/10";
            $tabMap.className = "px-3 py-1 rounded-lg bg-white/15 border border-white/20 text-white/90";
          }}
        }}
        if (tab === "map") {{
          initMapOnce();
          refreshVisibleMapViewport();
        }}
        if ($mapToolbar) {{
          if (tab === "map") $mapToolbar.classList.remove("hidden");
          else $mapToolbar.classList.add("hidden");
        }}
        if (tab !== "map" && $mapSearchSuggest) {{
          $mapSearchSuggest.classList.add("hidden");
        }}
        if ($provinceCurvePanel) {{
          if (tab === "map") {{
            $provinceCurvePanel.classList.remove("hidden");
            updateProvinceBars();
          }} else {{
            $provinceCurvePanel.classList.add("hidden");
          }}
        }}
      }};

      const CHINA_OVERVIEW_CENTER = [104.5, 36.0];
      const CHINA_OVERVIEW_ZOOM = 3.9;
      const isSpecialSunMarker = (n) => String((n && n.person) || "").trim() === "毛泽东";
      const isForeignPerson = (n) => Boolean(n && n.is_foreign);

      const markerSvg = (sz, fill, glow, emph) => {{
        const glowRadius = emph ? 10 : 6;
        return `<svg width="${{sz}}" height="${{sz}}" viewBox="0 0 24 24" style="overflow:visible;filter:drop-shadow(0 0 ${{glowRadius}}px ${{glow}});"><circle cx="12" cy="12" r="11" fill="rgba(255,255,255,0.001)"></circle><circle cx="12" cy="12" r="6.7" fill="${{fill}}"></circle><circle cx="12" cy="12" r="6.0" fill="${{fill}}" stroke="rgba(255,255,255,0.22)" stroke-width="0.9"></circle></svg>`;
      }};
      const foreignMarkerSvg = (sz, fill, glow, emph) => {{
        const glowRadius = emph ? 10 : 6;
        return `<svg width="${{sz}}" height="${{sz}}" viewBox="0 0 24 24" style="overflow:visible;filter:drop-shadow(0 0 ${{glowRadius}}px ${{glow}});"><rect x="2.5" y="2.5" width="19" height="19" rx="2.2" fill="rgba(255,255,255,0.001)"></rect><rect x="5.2" y="5.2" width="13.6" height="13.6" rx="1.8" fill="${{fill}}"></rect><rect x="5.8" y="5.8" width="12.4" height="12.4" rx="1.6" fill="${{fill}}" stroke="rgba(255,255,255,0.28)" stroke-width="0.9"></rect></svg>`;
      }};
      const markerHtml = (n, sz, fill, glow, emph) => {{
        if (isSpecialSunMarker(n)) return sunMarkerHtml(sz, glow, emph);
        if (isForeignPerson(n)) return foreignMarkerSvg(sz, fill, glow, emph);
        return markerSvg(sz, fill, glow, emph);
      }};

      const sunMarkerHtml = (sz, glow, emph) => {{
        const glowRadius = emph ? 12 : 8;
        const core = Math.max(7.2, sz * 0.4);
        const rayOuter = Math.max(core + 3.4, sz * 0.48);
        const rayInner = Math.max(core + 1.0, sz * 0.32);
        const stroke = Math.max(1.5, sz * 0.1);
        const center = sz / 2;
        const rays = Array.from({{ length: 8 }}, (_, idx) => {{
          const angle = (Math.PI * 2 * idx) / 8 - Math.PI / 2;
          const x1 = center + Math.cos(angle) * rayInner;
          const y1 = center + Math.sin(angle) * rayInner;
          const x2 = center + Math.cos(angle) * rayOuter;
          const y2 = center + Math.sin(angle) * rayOuter;
          return `<line x1="${{x1.toFixed(2)}}" y1="${{y1.toFixed(2)}}" x2="${{x2.toFixed(2)}}" y2="${{y2.toFixed(2)}}" stroke="rgba(251,191,36,0.98)" stroke-width="${{stroke.toFixed(2)}}" stroke-linecap="round"></line>`;
        }}).join("");
        return `<svg width="${{sz}}" height="${{sz}}" viewBox="0 0 ${{sz}} ${{sz}}" style="overflow:visible;filter:drop-shadow(0 0 ${{glowRadius}}px ${{glow}});"><circle cx="${{center}}" cy="${{center}}" r="${{core.toFixed(2)}}" fill="rgba(250,204,21,0.98)" stroke="rgba(255,255,255,0.92)" stroke-width="${{Math.max(1.4, sz * 0.08).toFixed(2)}}"></circle>${{rays}}</svg>`;
      }};

      const applyChinaOverview = () => {{
        try {{
          if (amap) amap.setZoomAndCenter(CHINA_OVERVIEW_ZOOM, CHINA_OVERVIEW_CENTER);
        }} catch (_) {{}}
      }};

      const initMapOnce = () => {{
        if (mapInited) return;
        if (!$chinaMap) return;
        if (!$chinaMap.style.position) $chinaMap.style.position = "relative";
        mapInited = true;
        _ensureAmap().then(() => {{
          if (!window.AMap) return;
          amap = new window.AMap.Map($chinaMap, {{
            zoom: CHINA_OVERVIEW_ZOOM,
            center: CHINA_OVERVIEW_CENTER,
            viewMode: "2D",
            mapStyle: mapStyleValue || "amap://styles/whitesmoke",
            resizeEnable: true,
          }});
          try {{
            if (typeof amap.on === "function") {{
              const markTouched = () => {{
                mapCameraTouched = true;
              }};
              amap.on("dragstart", () => {{
                markTouched();
                closeMarkerInfo();
                closeMapTip();
              }});
              amap.on("mousewheel", markTouched);
              amap.on("zoomstart", () => {{
                markTouched();
                closeMarkerInfo();
                closeMapTip();
              }});
              amap.on("touchstart", () => {{
                markTouched();
                closeMarkerInfo();
                closeMapTip();
              }});
              amap.on("click", () => {{
                closeMarkerInfo();
                closeMapTip();
              }});
            }}
          }} catch (_) {{}}
          try {{
            const heihe = [127.500, 50.250];
            const tengchong = [98.490, 25.020];
            const mid = [
              heihe[0] + (tengchong[0] - heihe[0]) / 3,
              heihe[1] + (tengchong[1] - heihe[1]) / 3,
            ];
            const line = new window.AMap.Polyline({{
              path: [heihe, tengchong],
              strokeColor: "rgba(249,115,22,0.92)",
              strokeWeight: 3,
              strokeStyle: "dashed",
              strokeDasharray: [10, 8],
              zIndex: 300,
            }});
            line.setMap(amap);
            const dx = tengchong[0] - heihe[0];
            const dy = tengchong[1] - heihe[1];
            const len = Math.hypot(dx, dy) || 1;
            let nx = (-dy) / len;
            let ny = dx / len;
            if (ny < 0) {{
              nx = -nx;
              ny = -ny;
            }}
            const offsetDeg = 1.32;
            const labelPos = [mid[0] + nx * offsetDeg, mid[1] + ny * offsetDeg];
            const ang = 0;
            const label = new window.AMap.Marker({{
              position: labelPos,
              anchor: "center",
              offset: new window.AMap.Pixel(0, -5),
              clickable: false,
              content:
                '<div style="transform:rotate(' +
                String(ang.toFixed(2)) +
                'deg);transform-origin:center;background:rgba(15,23,42,0.72);border:1px solid rgba(255,255,255,0.22);color:rgba(255,255,255,0.96);padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap">胡焕庸线</div>',
              zIndex: 320,
            }});
            label.setMap(amap);
            const mkText = (text, pos) => {{
              const t = new window.AMap.Text({{
                text,
                position: pos,
                offset: new window.AMap.Pixel(0, -16),
                style: {{
                  background: "rgba(255,255,255,0.92)",
                  border: "1px solid rgba(15,23,42,0.18)",
                  color: "rgba(15,23,42,0.92)",
                  padding: "4px 8px",
                  borderRadius: "2px",
                  fontSize: "12px",
                  fontWeight: "700",
                }},
                zIndex: 320,
              }});
              t.setMap(amap);
              return t;
            }};
            mkText("黑河", heihe);
            mkText("腾冲", tengchong);
          }} catch (_) {{}}
          const coordCache = readCoordCache();
          applyCoordCacheToNodes(coordCache);

          let infoWin = null;
          try {{
            infoWin = new window.AMap.InfoWindow({{ offset: new window.AMap.Pixel(0, -22) }});
          }} catch (_) {{
            infoWin = null;
          }}

          const buildMapPersonInfoHtml = (n) => {{
            const years = formatYearRange(n.birth_year, n.death_year);
            const dynasty = String(n.dynasty || "").trim();
            const bp = formatBirthplace(n.birthplace, n.birthplace_modern);
            const bpRaw = String(n.birthplace_raw || n.birthplace || "").trim();
            const nativePlace = formatBirthplace(n.native_place, n.native_place_modern);
            const placeCompareKey = value => String(value || "")
              .replace(/^今\s*/g, "")
              .replace(/[（(][^）)]*[）)]/g, "")
              .replace(/[省市县区州郡府道镇乡村]/g, "")
              .replace(/\s+/g, "")
              .trim();
            const showNativePlace = nativePlace && (!bp || placeCompareKey(nativePlace) !== placeCompareKey(bp));
            const birthplaceAmbiguous = /存疑|一说|或说|又说|另说|未详|不详/.test(bpRaw);
            const bpDisplay = bp && birthplaceAmbiguous && showNativePlace ? "存疑" : bp;
            const quote = stripMd(String(n.quote || "").trim());
            const review = stripMd(String(n.review || "").trim());
            const tagline = stripOuterQuotes(review || quote);
            const root = document.createElement("div");
            root.style.minWidth = "220px";
            root.style.maxWidth = "280px";
            const appendLine = (text, cssText) => {{
              const el = document.createElement("div");
              el.style.cssText = cssText;
              el.textContent = text;
              root.appendChild(el);
            }};
            appendLine(String(n.person || ""), "font-weight:800;color:#0f172a;font-size:14px");
            appendLine("生卒：" + years, "margin-top:4px;color:rgba(15,23,42,0.70);font-size:12px");
            if (dynasty) appendLine("时代：" + dynasty, "margin-top:4px;color:rgba(15,23,42,0.70);font-size:12px");
            if (bpDisplay) appendLine("出生地：" + bpDisplay, "margin-top:4px;color:rgba(15,23,42,0.70);font-size:12px");
            if (showNativePlace) appendLine("籍贯：" + nativePlace, "margin-top:4px;color:rgba(15,23,42,0.70);font-size:12px");
            if (tagline) appendLine("“" + tagline + "”", "margin-top:6px;color:rgba(245,158,11,0.95);font-size:12px;line-height:1.4");
            const actions = document.createElement("div");
            actions.style.marginTop = "8px";
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "打开人物页";
            button.style.cssText = "background:#0f172a;color:#fff;border:0;border-radius:10px;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer";
            button.addEventListener("click", () => {{
              openPerson(n && n.person ? n.person : "");
            }});
            actions.appendChild(button);
            root.appendChild(actions);
            return root;
          }};

          const openMarkerInfo = (n, lng, lat) => {{
            if (!infoWin) return;
            try {{
              infoWin.setContent(buildMapPersonInfoHtml(n));
              infoWin.open(amap, [lng, lat]);
            }} catch (_) {{}}
          }};

          const closeMarkerInfo = () => {{
            try {{
              if (infoWin) infoWin.close();
            }} catch (_) {{}}
          }};

          const createMarkerContent = (n, lng, lat) => {{
            const el = document.createElement("div");
            const active = inWindow(n);
            const base = colorByYear(n.time_year);
            const accent = base.startsWith("#") ? hexToRgba(base, 0.92) : base;
            const accentSoft = base.startsWith("#") ? hexToRgba(base, 0.62) : base;
            const glowStrong = base.startsWith("#") ? hexToRgba(base, 0.40) : "rgba(154,160,166,0.22)";
            const glowSoft = base.startsWith("#") ? hexToRgba(base, 0.20) : "rgba(154,160,166,0.16)";
            const initialSize = active ? 20 : 18;
            const initialFill = active ? accent : accentSoft;
            const initialGlow = active ? glowStrong : glowSoft;
            el.style.width = "18px";
            el.style.height = "18px";
            el.style.display = "flex";
            el.style.alignItems = "center";
            el.style.justifyContent = "center";
            el.style.cursor = "pointer";
            el.style.pointerEvents = "auto";
            el.innerHTML = markerHtml(n, initialSize, initialFill, initialGlow, active);
            el.style.animation = active ? "twinkle 2.2s ease-in-out infinite" : "none";
            const show = (evt) => {{
              const pos = resolveMapTipClientPoint(evt, lng, lat);
              showMapTip(n, pos.clientX, pos.clientY);
            }};
            el.addEventListener("mouseenter", show);
            el.addEventListener("mousemove", show);
            el.addEventListener("mouseleave", () => {{
              closeMapTip();
            }});
            el.addEventListener("click", (evt) => {{
              if (evt && typeof evt.stopPropagation === "function") evt.stopPropagation();
              openMarkerInfo(n, lng, lat);
              show(evt);
            }});
            el.addEventListener("dblclick", (evt) => {{
              if (evt && typeof evt.stopPropagation === "function") evt.stopPropagation();
              openPerson(n.person);
            }});
            return el;
          }};

          // Keep markers as individual points so historical colors and hover cards stay visible.
          const addMarker = (n) => {{
            if (n && n._mapMarkerAdded) return;
            const latW = (typeof n.birth_lat_wgs84 === "number") ? n.birth_lat_wgs84 : n.birth_lat;
            const lngW = (typeof n.birth_lng_wgs84 === "number") ? n.birth_lng_wgs84 : n.birth_lng;
            if (typeof latW !== "number" || typeof lngW !== "number") return;
            const p = wgs84ToGcj02(latW, lngW);
            const lat = p.lat;
            const lng = p.lng;
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
            const markerEl = createMarkerContent(n, lng, lat);
            const mk = new window.AMap.Marker({{
              position: [lng, lat],
              offset: new window.AMap.Pixel(-9, -9),
              content: markerEl,
              anchor: "center",
              clickable: true,
            }});
            mk.on("mouseover", (evt) => {{
              const pos = resolveMapTipClientPoint(evt, lng, lat);
              showMapTip(n, pos.clientX, pos.clientY);
            }});
            mk.on("mousemove", (evt) => {{
              const pos = resolveMapTipClientPoint(evt, lng, lat);
              showMapTip(n, pos.clientX, pos.clientY);
            }});
            mk.on("mouseout", () => {{
              closeMapTip();
            }});
            mk.on("click", () => {{
              try {{
                openMarkerInfo(n, lng, lat);
              }} catch (_) {{}}
            }});
            mk.on("dblclick", () => openPerson(n.person));
            try {{ mk.setMap(amap); }} catch (_) {{}}
            if (onlyActiveMarkers && !inWindow(n)) {{
              try {{ mk.hide(); }} catch (_) {{}}
            }}
            n._mapMarkerAdded = true;
            markers.push({{ mk, n, el: markerEl }});
          }};

          for (const n of nodes) addMarker(n);
          updateCoordCount();
          clusterer = null;
          updateMapMarkers();
          mapCameraTouched = false;

          runSharedCoordFill(coordCache, addMarker);
        }}).catch((e) => {{
          mapInited = false;
          try {{ console.warn("[stellar-map] amap init failed", e); }} catch (_) {{}}
        }});
      }};

      const updateMapMarkers = () => {{
        try {{
          if (!mapInited || !amap) return;
          const hiIdx = selectedIdx >= 0 ? selectedIdx : (spotlightIdx >= 0 ? spotlightIdx : -1);
          const focusSet = hiIdx >= 0 ? (() => {{
            const s = new Set();
            s.add(hiIdx);
            for (const j of (neigh[hiIdx] || [])) s.add(j);
            return s;
          }})() : null;
          const searchActive = mapSearchHighlightSet.size > 0;
          let shownCount = 0;
          let hiddenCount = 0;
          let forcedVisibleCount = 0;
          for (const it of markers) {{
            const n = it.n;
            const idx = typeof n._idx === "number" ? n._idx : -1;
            const active = inWindow(n);
            const forceVisible = idx >= 0 && idx === hiIdx;
            const searchHit = searchActive && idx >= 0 && mapSearchHighlightSet.has(idx);
            if (forceVisible) forcedVisibleCount += 1;
            if (onlyActiveMarkers && !active && !forceVisible && !searchHit) {{
              hiddenCount += 1;
              try {{ it.mk.hide(); }} catch (_) {{}}
              continue;
            }}
            shownCount += 1;
            try {{ it.mk.show(); }} catch (_) {{}}
            const searchDim = searchActive && !searchHit && !forceVisible;
            const dim = (focusSet && idx >= 0 && !focusSet.has(idx)) || searchDim;
            const emph = (active || forceVisible || (searchActive && searchHit)) && !searchDim;
            const sz = dim ? 16 : (emph ? 20 : 18);
            const base = colorByYear(n.time_year);
            const accent = base.startsWith("#") ? hexToRgba(base, 0.92) : base;
            const accentSoft = base.startsWith("#") ? hexToRgba(base, 0.62) : base;
            const glowStrong = base.startsWith("#") ? hexToRgba(base, 0.40) : "rgba(154,160,166,0.22)";
            const glowSoft = base.startsWith("#") ? hexToRgba(base, 0.20) : "rgba(154,160,166,0.16)";
            const fill = dim ? "rgba(232,234,237,0.18)" : (emph ? accent : accentSoft);
            const glow = dim ? "rgba(154,160,166,0.08)" : (emph ? glowStrong : glowSoft);
            if (it.el) {{
              it.el.style.width = `${{sz}}px`;
              it.el.style.height = `${{sz}}px`;
              it.el.innerHTML = markerHtml(n, sz, fill, glow, emph);
              it.el.style.animation = (!dim && emph) ? "twinkle 2.2s ease-in-out infinite" : "none";
              try {{
                it.mk.setContent(it.el);
              }} catch (_) {{}}
            }} else {{
              it.mk.setContent(markerHtml(n, sz, fill, glow, emph));
            }}
            it.mk.setOffset(new window.AMap.Pixel(-Math.round(sz / 2), -Math.round(sz / 2)));
          }}
        }} catch (e) {{
          throw e;
        }}
      }};

      if ($tabGraph) $tabGraph.addEventListener("click", () => setTab("graph"));
      if ($tabMap) $tabMap.addEventListener("click", () => setTab("map"));
      if ($presetBar) {{
        $presetBar.addEventListener("click", (e) => {{
          const t = e && e.target ? e.target : null;
          const btn = t && t.closest ? t.closest("button[data-preset]") : null;
          const key = btn ? String(btn.getAttribute("data-preset") || "") : "";
          if (!key) return;
          const presets = getPresetRanges();
          const r = presets[key];
          if (!r) return;
          startYear = clamp(r[0], minYear, maxYear);
          endYear = clamp(r[1], minYear, maxYear);
          if (startYear >= endYear) endYear = clamp(startYear + 1, minYear, maxYear);
          setHandles();
          updateActiveCount();
          updateCoordCount();
          updateMapMarkers();
          draw();
        }});
      }}
      const resetMapView = () => {{
        try {{
          mapCameraTouched = false;
          applyChinaOverview();
        }} catch (_) {{}}
      }};
      if ($resetMap) $resetMap.addEventListener("click", resetMapView);

      let _mapSearchTimer = null;
      const _scheduleMapSearch = (val, opts) => {{
        if (_mapSearchTimer) clearTimeout(_mapSearchTimer);
        _mapSearchTimer = setTimeout(() => {{
          applyMapSearch(val, opts || {{}});
        }}, 140);
      }};
      if ($mapSearchInput) {{
        $mapSearchInput.addEventListener("input", (e) => {{
          const v = e && e.target ? String(e.target.value || "") : "";
          // 输入时同步缩放到匹配人物的边界框
          _scheduleMapSearch(v, {{ fit: true }});
        }});
        $mapSearchInput.addEventListener("focus", () => {{
          if (mapSearchQuery) renderMapSearchSuggest();
        }});
        $mapSearchInput.addEventListener("keydown", (e) => {{
          if (!$mapSearchSuggest) return;
          const key = e && e.key ? String(e.key) : "";
          if (key === "Enter") {{
            applyMapSearch($mapSearchInput.value || "", {{ fit: true }});
            if (mapSearchSuggestIdx >= 0) {{
              const items = collectMapSearchMatches($mapSearchInput.value || "", 30);
              const pick = items[mapSearchSuggestIdx];
              if (pick && pick.person) {{
                try {{ openPerson(pick.person); }} catch (_) {{}}
              }}
            }}
            if (e.preventDefault) e.preventDefault();
            return;
          }}
          if (key === "Escape") {{
            $mapSearchInput.value = "";
            applyMapSearch("", {{}});
            if (e.preventDefault) e.preventDefault();
            return;
          }}
          if (key === "ArrowDown" || key === "ArrowUp") {{
            const items = collectMapSearchMatches($mapSearchInput.value || "", 30);
            if (!items.length) return;
            if (key === "ArrowDown") mapSearchSuggestIdx = Math.min(items.length - 1, mapSearchSuggestIdx + 1);
            else mapSearchSuggestIdx = Math.max(0, mapSearchSuggestIdx - 1);
            renderMapSearchSuggest();
            if (e.preventDefault) e.preventDefault();
          }}
        }});
      }}
      if ($mapSearchClear) {{
        $mapSearchClear.addEventListener("click", () => {{
          if ($mapSearchInput) $mapSearchInput.value = "";
          applyMapSearch("", {{}});
          if ($mapSearchInput) $mapSearchInput.focus();
        }});
      }}
      if ($mapSearchSuggest) {{
        $mapSearchSuggest.addEventListener("mousedown", (e) => {{
          const t = e && e.target ? e.target : null;
          const row = t && t.closest ? t.closest("[data-mperson]") : null;
          if (!row) return;
          const person = String(row.getAttribute("data-mperson") || "").trim();
          if (!person) return;
          try {{ openPerson(person); }} catch (_) {{}}
        }});
      }}
      document.addEventListener("click", (e) => {{
        if (!$mapSearchSuggest || $mapSearchSuggest.classList.contains("hidden")) return;
        const t = e && e.target ? e.target : null;
        if ($mapSearchInput && t === $mapSearchInput) return;
        if (t && $mapSearchSuggest.contains(t)) return;
        $mapSearchSuggest.classList.add("hidden");
      }});

      setTab("graph");

      const onMouseMove = (e) => {{
        const rect = $c.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (W / rect.width);
        const my = (e.clientY - rect.top) * (H / rect.height);
        const n = pickNode(mx, my);
        hover = n;
        if (n) showTip(n, e.clientX, e.clientY);
        else showTip(null);
        draw();
      }};

      $c.addEventListener("mousemove", onMouseMove);
      $c.addEventListener("mouseleave", () => {{
        hover = null;
        showTip(null);
        draw();
      }});
      $c.addEventListener("click", (event) => {{
        const rect = $c.getBoundingClientRect();
        const mx = (event.clientX - rect.left) * (W / rect.width);
        const my = (event.clientY - rect.top) * (H / rect.height);
        const n = pickNode(mx, my);
        if (_clickTimer) clearTimeout(_clickTimer);
        _clickTimer = setTimeout(() => {{
          if (n) {{
            if (selected && typeof selected._idx === "number" && selected._idx === n._idx) {{
              openPerson(n.person);
              _clickTimer = null;
              return;
            }}
            setSelected(n);
          }} else {{
            setSelected(null);
          }}
          _clickTimer = null;
        }}, 220);
      }});
      $c.addEventListener("dblclick", (event) => {{
        if (_clickTimer) {{
          clearTimeout(_clickTimer);
          _clickTimer = null;
        }}
        const rect = $c.getBoundingClientRect();
        const mx = (event.clientX - rect.left) * (W / rect.width);
        const my = (event.clientY - rect.top) * (H / rect.height);
        const n = pickNode(mx, my);
        if (n) openPerson(n.person);
      }});

      let isPanning = false;
      let panStartX = 0;
      let panStartY = 0;
      let panStartOffX = 0;
      let panStartOffY = 0;
      $c.addEventListener("mousedown", (e) => {{
        if (!(e.button === 2 || (e.shiftKey && e.button === 0) || e.button === 1)) return;
        isPanning = true;
        panStartX = e.clientX;
        panStartY = e.clientY;
        panStartOffX = camOffX;
        panStartOffY = camOffY;
        try {{ e.preventDefault(); }} catch (_) {{}}
      }});
      $c.addEventListener("contextmenu", (e) => {{
        try {{ e.preventDefault(); }} catch (_) {{}}
      }});
      window.addEventListener("mouseup", () => {{
        isPanning = false;
      }});
      window.addEventListener("mousemove", (e) => {{
        if (!isPanning) return;
        camOffX = panStartOffX + (e.clientX - panStartX) * (W / $c.getBoundingClientRect().width);
        camOffY = panStartOffY + (e.clientY - panStartY) * (H / $c.getBoundingClientRect().height);
        draw();
      }});
      const railRect = () => $rail.getBoundingClientRect();

      const hitTestHandle = (e) => {{
        const r = railRect();
        const x = e.clientX - r.left;
        const {{x1, x2}} = handlePosPx();
        const px1 = x1;
        const px2 = x2;
        if (Math.abs(x - px1) < 18) return "left";
        if (Math.abs(x - px2) < 18) return "right";
        if (x > px1 && x < px2) return "mid";
        return "";
      }};

      const isEventWithinRail = (e) => {{
        if (!$rail || !e || typeof e.clientX !== "number" || typeof e.clientY !== "number") return false;
        const r = railRect();
        return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
      }};

      const onDown = (e) => {{
        if (typeof e.button === "number" && e.button !== 0) return;
        const r = railRect();
        const rx = clamp(e.clientX - r.left, 0, r.width || 1);
        const m = hitTestHandle(e);
        if (!m) {{
          dragMode = "brush";
          brushStartX = rx;
          brushStartYear = fromT(clamp(rx / (r.width || 1), 0, 1));
          startYear = brushStartYear;
          endYear = clamp(brushStartYear + 1, minYear, maxYear);
        }} else {{
          dragMode = m;
          dragStartX = e.clientX;
          dragStartA = startYear;
          dragStartB = endYear;
        }}
        if ($rail.setPointerCapture) {{
          try {{ $rail.setPointerCapture(e.pointerId); }} catch (_) {{}}
        }}
        if (e.stopPropagation) e.stopPropagation();
        e.preventDefault();
      }};

      const onMove = (e) => {{
        if (!dragMode) return;
        const r = railRect();
        if (dragMode === "brush") {{
          const rx = clamp(e.clientX - r.left, 0, r.width || 1);
          const y = fromT(clamp(rx / (r.width || 1), 0, 1));
          let a = Math.min(brushStartYear, y);
          let b = Math.max(brushStartYear, y);
          a = clamp(a, minYear, maxYear);
          b = clamp(b, minYear, maxYear);
          if (a === b) b = clamp(a + 1, minYear, maxYear);
          startYear = a;
          endYear = b;
        }} else {{
          const dx = e.clientX - dragStartX;
          const dt = dx / r.width;
          const span = dragStartB - dragStartA;
          if (dragMode === "left") {{
            const t = clamp(toT(dragStartA) + dt, 0, toT(dragStartB) - 0.01);
            startYear = fromT(t);
          }} else if (dragMode === "right") {{
            const t = clamp(toT(dragStartB) + dt, toT(dragStartA) + 0.01, 1);
            endYear = fromT(t);
          }} else if (dragMode === "mid") {{
            const spanT = Math.max(0.01, toT(dragStartB) - toT(dragStartA));
            const nextStartT = clamp(toT(dragStartA) + dt, 0, 1 - spanT);
            const nextEndT = clamp(nextStartT + spanT, spanT, 1);
            startYear = fromT(nextStartT);
            endYear = fromT(nextEndT);
          }}
        }}
        if (startYear >= endYear) {{
          if (dragMode === "left") startYear = endYear - 1;
          else endYear = startYear + 1;
        }}
        setHandles();
        updateActiveCount();
        updateCoordCount();
        updateMapMarkers();
        draw();
      }};

      const onUp = () => {{
        if (!dragMode) return;
        const wasBrush = (dragMode === "brush");
        dragMode = "";
        if (wasBrush && currentTab === "graph") draw();
      }};

      const routeDown = (e) => {{
        if (!isEventWithinRail(e)) return;
        onDown(e);
      }};
      document.addEventListener("pointerdown", routeDown, true);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      document.addEventListener("mousedown", routeDown, true);
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      $rail.addEventListener("dblclick", () => {{
        startYear = 0;
        endYear = 1840;
        setHandles();
        updateActiveCount();
        updateCoordCount();
        updateMapMarkers();
        draw();
      }});
      if ($startYearInput) {{
        $startYearInput.addEventListener("keydown", (e) => {{
          if (e.key === "Enter") applyYearInputs();
        }});
        $startYearInput.addEventListener("change", applyYearInputs);
        $startYearInput.addEventListener("blur", applyYearInputs);
      }}
      if ($endYearInput) {{
        $endYearInput.addEventListener("keydown", (e) => {{
          if (e.key === "Enter") applyYearInputs();
        }});
        $endYearInput.addEventListener("change", applyYearInputs);
        $endYearInput.addEventListener("blur", applyYearInputs);
      }}
      window.addEventListener("resize", () => {{
        syncCanvasSize();
        renderBands();
        setHandles();
        syncSearchActionState();
        draw();
      }});

      const groupKey = (n) => {{
        const role = String(n.main_role_band || "").trim();
        if (role) return role;
        const d = String(n.dynasty || "").trim();
        if (d) return d.slice(0, 6);
        const name = String(n.person || "").trim();
        return name ? name.slice(0, 1) : "？";
      }};

      const buildNeigh = () => {{
        neigh = Array.from({{ length: nodes.length }}, () => []);
        edgeMeta = new Map();
        for (const e of edges) {{
          if (!e) continue;
          const a = e.a;
          const b = e.b;
          if (typeof a !== "number" || typeof b !== "number") continue;
          if (!neigh[a]) neigh[a] = [];
          if (!neigh[b]) neigh[b] = [];
          neigh[a].push(b);
          neigh[b].push(a);
          const lo = Math.min(a, b);
          const hi = Math.max(a, b);
          const k = `${{lo}},${{hi}}`;
          const conf = edgeConf(e);
          const label = String((e && e.label) || "").trim();
          const t = edgeType(e);
          const prev = edgeMeta.get(k) || null;
          if (!prev || conf >= (prev.confidence || 0)) {{
            edgeMeta.set(k, {{ label, confidence: conf, type: t }});
          }}
        }}
      }};

      migrateCoordCache();
      fetch(DATA_FILE).then((r) => r.json()).then((data) => {{
        searchCapabilities = Object.assign({{ aliases: true, foreign_name: true, pinyin: false }}, data.search_capabilities || {{}});
        setSearchHint();
        minYear = data.min_year ?? -800;
        maxYear = data.max_year ?? 1840;
        const raw = (data.nodes || []);
        const roleBandOrder = Array.isArray(data.role_band_order) && data.role_band_order.length
          ? data.role_band_order
          : ["military", "politics", "literature", "thought", "science", "art", "other"];
        const roleBandIndex = new Map(roleBandOrder.map((key, idx) => [String(key || "").trim(), idx]));
        const laneFor = (n) => {{
          const band = String(n.main_role_band || "").trim();
          const idx = roleBandIndex.has(band) ? roleBandIndex.get(band) : (roleBandOrder.length - 1);
          return (idx + 0.5) / Math.max(1, roleBandOrder.length);
        }};
        const laneJitter = (n) => {{
          const bandCount = Math.max(1, roleBandOrder.length);
          const bandHeight = (H - pad * 2) / bandCount;
          const seed = hash(String(n.person || ""));
          const dynastySeed = hash(String(n.dynasty || ""));
          const local = (rand01(seed + 2) - 0.5) * bandHeight * 0.42;
          const dynastyBias = ((Math.abs(dynastySeed) % 5) - 2) * Math.min(6, bandHeight * 0.08);
          return local + dynastyBias;
        }};

        const cell = 12;
        const occ = new Set();
        const key = (cx, cy) => `${{cx}},${{cy}}`;
        const isFree = (x, y) => {{
          const cx = Math.round(x / cell);
          const cy = Math.round(y / cell);
          const k = key(cx, cy);
          if (occ.has(k)) return false;
          occ.add(k);
          return true;
        }};

        const placeAtY = (dy, wantX, wantY) => {{
          const x = clamp(wantX, pad, W - pad);
          const y = clamp(wantY + dy, pad, H - pad);
          if (isFree(x, y)) return [x, y];
          return null;
        }};

        const offsets = [];
        offsets.push(0);
        for (let r = 1; r <= 12; r++) {{
          const step = 10;
          offsets.push(r * step, -r * step);
        }}

        nodes = raw.map((n, idx) => {{
          const seed = hash(n.person || "");
          const my = mainYear(n);
          const t = (typeof my === "number" && Number.isFinite(my)) ? clamp(toT(my), 0, 1) : null;
          const x0 = t == null ? (pad + rand01(seed + 1) * (W - pad * 2)) : (pad + t * (W - pad * 2));
          const yLane = laneFor(n);
          const y0 = pad + yLane * (H - pad * 2) + laneJitter(n);

          let best = null;
          for (const dy of offsets) {{
            const p = placeAtY(dy, x0, y0);
            if (p) {{ best = p; break; }}
          }}
          if (!best) {{
            best = [clamp(x0, pad, W - pad), clamp(y0, pad, H - pad)];
          }}
          const x = best[0];
          const y = best[1];
          return {{ ...n, x, y, bx: x, by: y, _idx: idx }};
        }});
        edgesAll = [];
        startYear = data.default_start ?? 100;
        endYear = data.default_end ?? 1600;
        startYear = clamp(Math.round(startYear), YEAR_INPUT_MIN, YEAR_INPUT_MAX);
        endYear = clamp(Math.round(endYear), YEAR_INPUT_MIN, YEAR_INPUT_MAX);
        if (startYear >= endYear) endYear = clamp(startYear + 1, YEAR_INPUT_MIN, YEAR_INPUT_MAX);
        timeWindowSignature = [minYear, maxYear, startYear, endYear].join(":");
        clearLegacyTimeWindow();
        applyEdgeFilters();
        renderBands();
        setHandles();
        updateActiveCount();
        updateCoordCount();
        prefillCoordsNoMap();
        syncSearchActionState();
        window.requestAnimationFrame(animate);
        if (DATA_DETAIL_FILE) {{
          if (typeof window.requestIdleCallback === "function") {{
            window.requestIdleCallback(() => loadHomeDetailData(), {{ timeout: 1200 }});
          }} else {{
            window.setTimeout(() => loadHomeDetailData(), 180);
          }}
        }}
      }});
    </script>
  </body>
</html>
"""


def _sync_vendor_assets(story_map_dir: Path) -> None:
    src = REPO_ROOT / "vendor"
    if not src.is_dir():
        return
    shutil.copytree(src, story_map_dir / "vendor", dirs_exist_ok=True)


def _sync_embedded_apps(story_map_dir: Path) -> None:
    syncer = _sync_orange_office_ui_impl
    if not callable(syncer):
        return
    try:
        syncer(story_map_dir)
    except FileNotFoundError:
        return


def _sync_homepage_pet_asset(story_map_dir: Path) -> None:
    for src in HOMEPAGE_PET_ASSET_CANDIDATES:
        if src.is_file():
            shutil.copy2(src, story_map_dir / HOMEPAGE_PET_ASSET_OUTPUT_NAME)
            return


def _prepare_home_payload_for_output(base_payload: Dict[str, Any], *, default_start: int, default_end: int) -> Dict[str, Any]:
    try:
        min_year = int(base_payload.get("min_year")) if base_payload.get("min_year") not in (None, "") else None
    except Exception:
        min_year = None
    try:
        max_year = int(base_payload.get("max_year")) if base_payload.get("max_year") not in (None, "") else None
    except Exception:
        max_year = None
    nodes = base_payload.get("nodes") if isinstance(base_payload.get("nodes"), list) else []
    normalized_nodes: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        normalized = dict(node)
        normalized["is_foreign"] = _is_foreign_person(
            foreign_name=str(normalized.get("foreign_name") or ""),
            birthplace_modern=str(normalized.get("birthplace_modern") or ""),
            birthplace_raw=str(normalized.get("birthplace_raw") or ""),
            dynasty=str(normalized.get("dynasty") or ""),
        )
        normalized_nodes.append(normalized)
    edges = base_payload.get("edges") if isinstance(base_payload.get("edges"), list) else []
    kg_edges = base_payload.get("kg_edges") if isinstance(base_payload.get("kg_edges"), list) else []
    return {
        **_build_payload_meta(),
        "min_year": min_year if min_year is not None else MIN_YEAR,
        "max_year": max_year if max_year is not None else MAX_YEAR,
        "default_start": int(default_start),
        "default_end": int(default_end),
        "role_band_order": ROLE_BAND_ORDER,
        "role_band_labels": ROLE_BAND_LABELS,
        "search_capabilities": {
            "aliases": True,
            "foreign_name": True,
            "pinyin": HAS_PINYIN,
        },
        "nodes": normalized_nodes,
        "edges": edges,
        "kg_edges": kg_edges,
    }


def _derive_home_detail_file_name(out_data_name: str) -> str:
    path = Path(str(out_data_name or "stellar_home_data.json"))
    suffix = path.suffix or ".json"
    stem = path.stem or "stellar_home_data"
    return f"{stem}_detail{suffix}"


def _split_home_payload_for_delivery(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    core_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    detail_payload: Dict[str, Any] = {
        **_build_payload_meta(),
        "fields": list(HOME_DETAIL_NODE_FIELDS),
        "nodes": [],
    }
    nodes = core_payload.get("nodes") if isinstance(core_payload.get("nodes"), list) else []
    detail_nodes: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        detail_node: Dict[str, Any] = {}
        for field in HOME_DETAIL_NODE_FIELDS:
            if field in node:
                detail_node[field] = node.pop(field)
        if detail_node:
            detail_node["person"] = str(node.get("person") or "").strip()
            detail_node["file"] = str(node.get("file") or "").strip()
            detail_nodes.append(detail_node)
    detail_payload["nodes"] = detail_nodes
    detail_payload["count"] = len(detail_nodes)
    return core_payload, detail_payload


def _write_homepage_outputs(
    *,
    story_map_dir: Path,
    out_index_name: str,
    out_data_name: str,
    title: str,
    payload: Dict[str, Any],
    active_redirects: Dict[str, str],
    sync_payload_to_neo4j: bool,
) -> Dict[str, Any]:
    out_data = story_map_dir / str(out_data_name)
    out_detail = story_map_dir / _derive_home_detail_file_name(str(out_data_name))
    out_index = story_map_dir / str(out_index_name)
    core_payload, detail_payload = _split_home_payload_for_delivery(payload)
    if write_normalized_graph_json:
        try:
            write_normalized_graph_json(payload, GRAPH_ARTIFACT_DIR / "normalized_graph.json")
        except Exception:
            pass
    if sync_payload_to_neo4j and should_sync_to_neo4j and sync_graph_payload_to_neo4j:
        try:
            if should_sync_to_neo4j():
                sync_graph_payload_to_neo4j(payload, replace=True)
        except Exception:
            pass
    out_data.write_text(json.dumps(core_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_detail.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_index.write_text(_render_index_html(title, out_data.name, out_detail.name), encoding="utf-8")
    _remove_person_alias_redirect_pages(story_map_dir, active_redirects)
    _sync_vendor_assets(story_map_dir)
    _sync_embedded_apps(story_map_dir)
    _sync_homepage_pet_asset(story_map_dir)
    return {
        "index": str(out_index),
        "data": str(out_data),
        "detail": str(out_detail),
        "count": len(core_payload.get("nodes") if isinstance(core_payload.get("nodes"), list) else []),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--story-map-dir", default=str(STORY_MAP_DIR))
    p.add_argument("--story-md-dir", default=str(STORY_MD_DIR))
    p.add_argument("--summary-index", "--spotlight", dest="summary_index", default=str(SUMMARY_INDEX_JSON))
    p.add_argument("--out-index", default="index.html")
    p.add_argument("--out-data", default="stellar_home_data.json")
    p.add_argument("--title", default="故事地图")
    p.add_argument("--default-start", type=int, default=100)
    p.add_argument("--default-end", type=int, default=1600)
    p.add_argument("--graph-source", choices=("auto", "build", "neo4j"), default="auto")
    args = p.parse_args()

    story_map_dir = Path(args.story_map_dir).resolve()
    story_md_dir = Path(args.story_md_dir).resolve()
    summary_index_path = Path(getattr(args, "summary_index", getattr(args, "spotlight", ""))).resolve()

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(dotenv_path=str((REPO_ROOT / ".env").resolve()))
        load_dotenv(dotenv_path=str((REPO_ROOT.parent / ".env").resolve()))
        load_dotenv(dotenv_path=str((REPO_ROOT.parent.parent / ".env").resolve()))
        load_dotenv(dotenv_path=str((REPO_ROOT / "data" / ".env").resolve()))
    except Exception:
        pass
    if apply_story_map_env_aliases:
        apply_story_map_env_aliases()

    latest_html = _scan_latest_html(story_map_dir)
    geocode_city = None
    try:
        sys.path.insert(0, str((REPO_ROOT / "storymap" / "script").resolve()))
        from storymap.script.map.map_client import geocode_city as _geocode_city  # type: ignore

        geocode_city = _geocode_city
    except Exception:
        geocode_city = None
    geocode_limit = int(os.getenv("STELLAR_HOME_GEOCODE_LIMIT", "0") or "0")
    geocode_used = 0

    hist_index_path = data_corpus_file_path("historical_places_index.jsonl").resolve()
    hist_index: Dict[str, Tuple[float, float]] = {}

    def _norm_place_key(s: str) -> str:
        t = str(s or "").strip()
        if not t:
            return ""
        t = re.sub(r"[\\s\\(\\)（）\\[\\]【】<>《》“”‘’\"'·•,，。；;:：/\\\\-—]+", "", t)
        return t.strip().lower()

    def _load_hist_index() -> Dict[str, Tuple[float, float]]:
        if not hist_index_path.exists():
            return {}
        mapping: Dict[str, Tuple[float, float]] = {}
        try:
            with hist_index_path.open("r", encoding="utf-8") as f:
                for line in f:
                    s = (line or "").strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    ancient = str(obj.get("ancient_name") or "").strip()
                    modern = str(obj.get("modern_name") or "").strip()
                    lat = obj.get("lat")
                    lon = obj.get("lon")
                    try:
                        lat_f = float(lat)
                        lon_f = float(lon)
                    except Exception:
                        continue
                    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
                        continue
                    for key in (ancient, modern):
                        nk = _norm_place_key(key)
                        if nk and nk not in mapping:
                            mapping[nk] = (lat_f, lon_f)
        except Exception:
            return {}
        return mapping

    hist_index = _load_hist_index()

    person_birth_coords: Dict[str, Tuple[float, float]] = {}
    try:
        if BIRTH_COORDS_WGS84_JSON.exists():
            raw_pbc = json.loads(BIRTH_COORDS_WGS84_JSON.read_text(encoding="utf-8"))
            if isinstance(raw_pbc, dict):
                for k, v in raw_pbc.items():
                    name = str(k or "").strip()
                    if not name:
                        continue
                    if isinstance(v, list) and len(v) >= 2:
                        try:
                            lat = float(v[0])
                            lng = float(v[1])
                        except Exception:
                            continue
                        if -90 <= lat <= 90 and -180 <= lng <= 180:
                            person_birth_coords[name] = (lat, lng)
    except Exception:
        person_birth_coords = {}

    person_birth_coords_dirty = 0

    def _set_person_birth_coord(person: str, lat: float, lng: float) -> None:
        nonlocal person_birth_coords_dirty
        p = str(person or "").strip()
        if not p:
            return
        try:
            la = float(lat)
            lo = float(lng)
        except Exception:
            return
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            return
        old = person_birth_coords.get(p)
        if old and abs(old[0] - la) < 1e-7 and abs(old[1] - lo) < 1e-7:
            return
        person_birth_coords[p] = (la, lo)
        person_birth_coords_dirty += 1

    def _clear_person_birth_coord(person: str) -> None:
        nonlocal person_birth_coords_dirty
        p = str(person or "").strip()
        if not p or p not in person_birth_coords:
            return
        person_birth_coords.pop(p, None)
        person_birth_coords_dirty += 1

    def _hist_lookup(*names: str) -> Optional[Tuple[float, float]]:
        for name in names:
            nk = _norm_place_key(name)
            if not nk:
                continue
            coord = hist_index.get(nk)
            if coord:
                return coord
        return None

    def _lookup_birth_coord_from_coords_table(
        coords_table: Dict[str, Tuple[float, float]],
        birthplace_modern: str,
        birthplace_ancient: str,
        birthplace_raw: str,
    ) -> Optional[Tuple[float, float]]:
        # Try both the cleaned birthplace text and its parenthetical-stripped variant because
        # markdown coordinate tables may store either form.
        for term in _birthplace_lookup_terms(birthplace_modern, birthplace_ancient, birthplace_raw):
            nk = _norm_place_key(term)
            if not nk:
                continue
            if nk in coords_table:
                return coords_table[nk]
            for coord_key, coord_value in coords_table.items():
                if not coord_key:
                    continue
                if (coord_key in nk) or (nk in coord_key):
                    return coord_value
        return None

    def _lookup_birth_coord_from_hist_index(
        birthplace_modern: str,
        birthplace_ancient: str,
        birthplace_raw: str,
    ) -> Optional[Tuple[float, float]]:
        terms = _birthplace_lookup_terms(birthplace_modern, birthplace_ancient, birthplace_raw)
        if not terms:
            return None
        return _hist_lookup(*terms)

    def _parse_coords_table_from_md(md_text: str) -> Dict[str, Tuple[float, float]]:
        if not isinstance(md_text, str) or not md_text.strip():
            return {}
        lines = md_text.splitlines()
        in_section = False
        table_started = False
        idx_name = None
        idx_lat = None
        idx_lng = None
        out: Dict[str, Tuple[float, float]] = {}
        for line in lines:
            s = (line or "").strip()
            if s.startswith("## "):
                title = s.lstrip("#").strip()
                in_section = "地点坐标" in title
                table_started = False
                idx_name = None
                idx_lat = None
                idx_lng = None
                continue
            if not in_section:
                continue
            if s.startswith("|") and (not table_started):
                header = [c.strip() for c in s.strip("|").split("|")]
                for i, c in enumerate(header):
                    cl = c.lower()
                    if ("现称" in c) or ("地点" in c) or ("location" in cl) or ("place" in cl):
                        idx_name = i
                    if ("纬度" in c) or ("lat" in cl):
                        idx_lat = i
                    if ("经度" in c) or ("lng" in cl) or ("lon" in cl) or ("long" in cl):
                        idx_lng = i
                table_started = True
                continue
            if table_started:
                if (not s) or (not s.startswith("|")):
                    break
                cols = [c.strip() for c in s.strip("|").split("|")]
                if idx_name is None or idx_lat is None or idx_lng is None:
                    continue
                if idx_name >= len(cols) or idx_lat >= len(cols) or idx_lng >= len(cols):
                    continue
                name = cols[idx_name]
                if re.fullmatch(r":?-+:?", cols[idx_lat].replace(" ", "")) or re.fullmatch(
                    r":?-+:?", cols[idx_lng].replace(" ", "")
                ):
                    continue
                try:
                    lat = float(cols[idx_lat])
                    lng = float(cols[idx_lng])
                except Exception:
                    continue
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    continue
                raw_name = str(name or "").strip()
                variants = [raw_name]
                try:
                    stripped = re.sub(r"[（(].*?[）)]", "", raw_name).strip()
                    if stripped and stripped not in variants:
                        variants.append(stripped)
                    if "（" in raw_name:
                        left = raw_name.split("（", 1)[0].strip()
                        if left and left not in variants:
                            variants.append(left)
                    if "(" in raw_name:
                        left = raw_name.split("(", 1)[0].strip()
                        if left and left not in variants:
                            variants.append(left)
                    label_stripped = re.sub(r"^(?:出生地|去世地|重要地点)[:：]\s*", "", raw_name).strip()
                    if label_stripped and label_stripped not in variants:
                        variants.append(label_stripped)
                    label_stripped_plain = re.sub(r"[（(].*?[）)]", "", label_stripped).strip()
                    if label_stripped_plain and label_stripped_plain not in variants:
                        variants.append(label_stripped_plain)
                except Exception:
                    pass
                for v in variants:
                    nk = _norm_place_key(v)
                    if nk and nk not in out:
                        out[nk] = (lat, lng)
        return out

    amap_key = (
        os.getenv("locaion_api")
        or os.getenv("location_api")
        or os.getenv("LOCATION_API")
        or os.getenv("AMAP_WEBSERVICE_KEY")
        or os.getenv("AMAP_WEB_SERVICE_KEY")
        or os.getenv("AMAP_REST_KEY")
        or ""
    ).strip()
    amap_limit = int(os.getenv("STELLAR_HOME_AMAP_GEOCODE_LIMIT", "5000") or "5000")
    amap_interval_s = float(os.getenv("STELLAR_HOME_AMAP_MIN_INTERVAL", "0.08") or "0.08")
    amap_concurrency = int(os.getenv("STELLAR_HOME_AMAP_CONCURRENCY", "6") or "6")
    amap_qps = float(os.getenv("STELLAR_HOME_AMAP_QPS", "8") or "8")
    if not (amap_concurrency > 0):
        amap_concurrency = 1
    if not (amap_qps > 0):
        amap_qps = 8.0
    amap_min_interval_s = max(amap_interval_s, 1.0 / float(amap_qps))
    amap_req_used = 0
    amap_last_ts = 0.0
    amap_lock = threading.Lock()
    amap_cache_path = (REPO_ROOT / "cache" / "amap_geocode_cache.json").resolve()
    amap_cache: Dict[str, Optional[Tuple[float, float]]] = {}
    try:
        if amap_cache_path.exists():
            raw_cache = json.loads(amap_cache_path.read_text(encoding="utf-8"))
            if isinstance(raw_cache, dict):
                for k, v in raw_cache.items():
                    if not isinstance(k, str) or not k.strip():
                        continue
                    kk = k.strip()
                    if v is None:
                        amap_cache[kk] = None
                        continue
                    if isinstance(v, list) and len(v) >= 2:
                        try:
                            lat = float(v[0])
                            lng = float(v[1])
                        except Exception:
                            continue
                        if -90 <= lat <= 90 and -180 <= lng <= 180:
                            amap_cache[kk] = (lat, lng)
    except Exception:
        amap_cache = {}

    def _amap_geocode(address: str) -> Optional[Tuple[float, float]]:
        nonlocal amap_last_ts, amap_req_used
        addr = str(address or "").strip()
        if not addr or not amap_key:
            return None
        retry_none = str(os.getenv("STELLAR_HOME_AMAP_RETRY_NONE", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        if addr in amap_cache and (amap_cache.get(addr) is not None or (not retry_none)):
            return amap_cache.get(addr)
        with amap_lock:
            if amap_req_used >= amap_limit:
                return None
            amap_req_used += 1
            now = time.time()
            wait = (amap_last_ts + amap_min_interval_s) - now
            amap_last_ts = max(amap_last_ts, now) + amap_min_interval_s
        if wait > 0:
            time.sleep(wait)
        url = (
            "https://restapi.amap.com/v3/geocode/geo"
            f"?address={url_quote(addr, safe='')}&key={url_quote(amap_key, safe='')}"
        )
        try:
            req = Request(url, headers={"User-Agent": "StoryMap/1.0"})
            with urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            amap_cache[addr] = None
            return None
        if not isinstance(data, dict) or str(data.get("status")) != "1":
            amap_cache[addr] = None
            return None
        geocodes = data.get("geocodes")
        if not isinstance(geocodes, list) or not geocodes:
            amap_cache[addr] = None
            return None
        g0 = geocodes[0] if isinstance(geocodes[0], dict) else None
        if not isinstance(g0, dict):
            amap_cache[addr] = None
            return None
        loc = str(g0.get("location") or "").strip()
        if not loc or "," not in loc:
            amap_cache[addr] = None
            return None
        a, b = loc.split(",", 1)
        try:
            lng = float(a.strip())
            lat = float(b.strip())
        except Exception:
            amap_cache[addr] = None
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            amap_cache[addr] = None
            return None
        res = (lat, lng)
        amap_cache[addr] = res
        return res

    def _looks_foreign_query(q: str) -> bool:
        s = str(q or "").strip()
        if not s:
            return False
        if re.search(r"[A-Za-z]", s):
            return True
        return bool(
            re.search(
                r"(美国|智利|法国|英国|俄罗斯|希腊|乌克兰|西班牙|意大利|德国|日本|韩国|朝鲜|越南|泰国|缅甸|斯里兰卡|印度尼西亚|印度|巴西|阿根廷|墨西哥|古巴|加拿大|澳大利亚|新西兰|南非|埃及|以色列|巴勒斯坦|土耳其|伊朗|伊拉克|叙利亚|阿富汗|巴基斯坦|挪威|瑞典|芬兰|丹麦|冰岛|荷兰|比利时|瑞士|奥地利|葡萄牙|波兰|捷克|匈牙利|罗马尼亚|保加利亚|塞尔维亚|克罗地亚|爱尔兰|苏联)",
                s,
            )
        )

    def _looks_like_geocode_query(q: str) -> bool:
        s = str(q or "").strip()
        if not s:
            return False
        if _looks_foreign_query(s):
            return False
        if re.search(r"(存疑|不详|无法确认|具体地点存疑|未知|待查证|无考|虚构|传说|小说|人物|文学作品|作品|未明确|未记载|记载有限|背景设定)", s):
            return False
        if _looks_like_date_or_period_text(s):
            return False
        return True

    def _finalize_geocode_query(
        raw_query: str,
        *,
        extra_prefix_pattern: str = "",
        split_markers: str = "",
    ) -> str:
        # Normalize birthplace prose into a stable geocode query so the AMap/foreign/local fallback
        # branches do not quietly diverge over time.
        q = _strip_common_birthplace_prefixes(raw_query)
        if extra_prefix_pattern:
            q = re.sub(extra_prefix_pattern, "", q).strip()
        q = re.sub(r"^(?:出生地|出生地是|出生地点|籍贯|祖籍|故里)[:：\\s]*", "", q).strip()
        q = re.sub(r"^(?:今|现)?属\\s*", "", q).strip()
        q = re.sub(r"^(?:今|现)?为\\s*", "", q).strip()
        q = _strip_parenthetical_place_text(q)
        base_split_markers = "当时|现|今|属|位于|位在|坐落于|附近|一带|境内|范围内|大致在"
        if split_markers:
            base_split_markers = f"{base_split_markers}|{split_markers}"
        q = re.split(rf"(?:{base_split_markers})", q, maxsplit=1)[0].strip()
        q = q.split("，", 1)[0].split(",", 1)[0].split("；", 1)[0].split(";", 1)[0].strip()
        return q

    def _make_geocode_query(birthplace_modern: str, birthplace_ancient: str, birthplace_raw: str) -> str:
        return _finalize_geocode_query(birthplace_modern or birthplace_ancient or birthplace_raw or "")

    def _amap_geocode_batch(addresses: List[str]) -> None:
        if not amap_key:
            return
        retry_none = str(os.getenv("STELLAR_HOME_AMAP_RETRY_NONE", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        uniq: List[str] = []
        seen = set()
        for a in addresses:
            s = str(a or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            if s in amap_cache and (amap_cache.get(s) is not None or (not retry_none)):
                continue
            if not _looks_like_geocode_query(s):
                amap_cache[s] = None
                continue
            uniq.append(s)
        if not uniq:
            return

        def worker(addr: str) -> Tuple[str, Optional[Tuple[float, float]]]:
            return (addr, _amap_geocode(addr))

        with ThreadPoolExecutor(max_workers=amap_concurrency) as ex:
            futs = [ex.submit(worker, a) for a in uniq]
            for fut in as_completed(futs):
                try:
                    addr, res = fut.result()
                except Exception:
                    continue
                if not addr:
                    continue
                if addr not in amap_cache:
                    amap_cache[addr] = res
                    continue
                if retry_none and amap_cache.get(addr) is None and res is not None:
                    amap_cache[addr] = res

    foreign_limit = int(os.getenv("STELLAR_HOME_FOREIGN_GEOCODE_LIMIT", "1500") or "1500")
    foreign_concurrency = int(os.getenv("STELLAR_HOME_FOREIGN_CONCURRENCY", "6") or "6")
    foreign_qps = float(os.getenv("STELLAR_HOME_FOREIGN_QPS", "6") or "6")
    if not (foreign_concurrency > 0):
        foreign_concurrency = 1
    if not (foreign_qps > 0):
        foreign_qps = 6.0
    foreign_min_interval_s = max(1.0 / float(foreign_qps), 0.05)
    foreign_req_used = 0
    foreign_last_ts = 0.0
    foreign_lock = threading.Lock()
    foreign_cache_path = (REPO_ROOT / "cache" / "foreign_geocode_cache.json").resolve()
    foreign_cache: Dict[str, Optional[Tuple[float, float]]] = {}
    try:
        if foreign_cache_path.exists():
            raw_cache = json.loads(foreign_cache_path.read_text(encoding="utf-8"))
            if isinstance(raw_cache, dict):
                for k, v in raw_cache.items():
                    if not isinstance(k, str) or not k.strip():
                        continue
                    kk = k.strip()
                    if v is None:
                        foreign_cache[kk] = None
                        continue
                    if isinstance(v, list) and len(v) >= 2:
                        try:
                            lat = float(v[0])
                            lng = float(v[1])
                        except Exception:
                            continue
                        if -90 <= lat <= 90 and -180 <= lng <= 180:
                            foreign_cache[kk] = (lat, lng)
    except Exception:
        foreign_cache = {}

    def _looks_like_foreign_geocode_query(q: str) -> bool:
        s = str(q or "").strip()
        if not s:
            return False
        if not _looks_foreign_query(s):
            return False
        if re.search(r"(存疑|不详|无法确认|具体地点存疑|未知)", s):
            return False
        if _looks_like_date_or_period_text(s):
            return False
        return True

    def _foreign_geocode(address: str) -> Optional[Tuple[float, float]]:
        nonlocal foreign_last_ts, foreign_req_used
        addr = str(address or "").strip()
        if not addr:
            return None
        retry_none = str(os.getenv("STELLAR_HOME_FOREIGN_RETRY_NONE", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        if addr in foreign_cache:
            cached = foreign_cache.get(addr)
            if cached is not None or (not retry_none):
                return cached
        with foreign_lock:
            if foreign_req_used >= foreign_limit:
                return None
            foreign_req_used += 1
            now = time.time()
            wait = (foreign_last_ts + foreign_min_interval_s) - now
            foreign_last_ts = max(foreign_last_ts, now) + foreign_min_interval_s
        if wait > 0:
            time.sleep(wait)
        data = None
        try:
            url = f"https://photon.komoot.io/api/?limit=1&q={url_quote(addr, safe='')}"
            req = Request(url, headers={"User-Agent": "StoryMap/1.0"})
            with urlopen(req, timeout=18) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            data = None
        lat = None
        lng = None
        if isinstance(data, dict):
            feats = data.get("features")
            if isinstance(feats, list) and feats:
                f0 = feats[0] if isinstance(feats[0], dict) else None
                geom = f0.get("geometry") if isinstance(f0, dict) else None
                coords = geom.get("coordinates") if isinstance(geom, dict) else None
                if isinstance(coords, list) and len(coords) >= 2:
                    try:
                        lng = float(coords[0])
                        lat = float(coords[1])
                    except Exception:
                        lat = None
                        lng = None
        if lat is None or lng is None:
            try:
                url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={url_quote(addr, safe='')}"
                req = Request(url, headers={"User-Agent": "StoryMap/1.0"})
                with urlopen(req, timeout=18) as resp:
                    data2 = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data2, list) and data2:
                    d0 = data2[0] if isinstance(data2[0], dict) else None
                    if isinstance(d0, dict):
                        lat = float(d0.get("lat"))
                        lng = float(d0.get("lon"))
            except Exception:
                lat = None
                lng = None
        if lat is None or lng is None:
            foreign_cache[addr] = None
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            foreign_cache[addr] = None
            return None
        res = (float(lat), float(lng))
        foreign_cache[addr] = res
        return res

    def _foreign_geocode_batch(addresses: List[str]) -> None:
        retry_none = str(os.getenv("STELLAR_HOME_FOREIGN_RETRY_NONE", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        uniq: List[str] = []
        seen = set()
        for a in addresses:
            s = str(a or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            if s in foreign_cache and (foreign_cache.get(s) is not None or (not retry_none)):
                continue
            if not _looks_like_foreign_geocode_query(s):
                foreign_cache[s] = None
                continue
            uniq.append(s)
        if not uniq:
            return

        def worker(addr: str) -> Tuple[str, Optional[Tuple[float, float]]]:
            return (addr, _foreign_geocode(addr))

        with ThreadPoolExecutor(max_workers=foreign_concurrency) as ex:
            futs = [ex.submit(worker, a) for a in uniq]
            for fut in as_completed(futs):
                try:
                    addr, res = fut.result()
                except Exception:
                    continue
                if not addr:
                    continue
                if addr not in foreign_cache:
                    foreign_cache[addr] = res
                    continue
                if retry_none and foreign_cache.get(addr) is None and res is not None:
                    foreign_cache[addr] = res

    md_names = _scan_people_from_story_md(story_md_dir)
    requested_graph_source = str(args.graph_source or "auto").strip().lower()
    configured_graph_backend = graph_backend_name() if graph_backend_name else "file"
    active_redirects = person_redirects(md_names) if md_names else {}

    should_try_neo4j = requested_graph_source == "neo4j" or (
        requested_graph_source == "auto" and configured_graph_backend == "neo4j"
    )
    if should_try_neo4j and load_home_graph_payload_with_source:
        try:
            graph_payload, graph_payload_source = load_home_graph_payload_with_source(
                backend="neo4j",
                strict_backend=(requested_graph_source == "neo4j"),
            )
        except Exception:
            graph_payload, graph_payload_source = {}, ""
        if (
            graph_payload_source == "neo4j"
            and isinstance(graph_payload, dict)
            and isinstance(graph_payload.get("nodes"), list)
            and graph_payload.get("nodes")
        ):
            payload = _prepare_home_payload_for_output(
                graph_payload,
                default_start=int(args.default_start),
                default_end=int(args.default_end),
            )
            outputs = _write_homepage_outputs(
                story_map_dir=story_map_dir,
                out_index_name=str(args.out_index),
                out_data_name=str(args.out_data),
                title=str(args.title),
                payload=payload,
                active_redirects=active_redirects,
                sync_payload_to_neo4j=False,
            )
            print(json.dumps({"ok": True, **outputs, "source": "neo4j"}, ensure_ascii=False))
            return 0
        if requested_graph_source == "neo4j":
            print(json.dumps({"ok": False, "error": "neo4j graph payload unavailable"}, ensure_ascii=False))
            return 1

    if not md_names:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"no story markdown found in {story_md_dir}",
                },
                ensure_ascii=False,
            )
        )
        return 1
    # 首页只给“仍然只是别名”的名字生成跳转页；如果它已经有真实 Markdown，
    # 就不能再被 redirect 覆盖。
    story_name_entries = _canonical_story_name_entries(md_names)

    spotlight_data = _read_json(summary_index_path) if summary_index_path.exists() and summary_index_path.is_file() else {}
    spotlight_items = spotlight_data.get("items") if isinstance(spotlight_data, dict) else {}
    if not isinstance(spotlight_items, dict):
        spotlight_items = {}
    work_summary_items = _load_work_summary_items(WORK_SUMMARY_INDEX_JSON)

    strict_audit_dir = (DATA_REPORTS_DIR / "validation_reports" / "strict_audit").resolve()

    def _load_person_audit(name: str) -> Tuple[str, object, object]:
        try:
            report_path = strict_audit_dir / f"{name}.json"
            if not report_path.exists():
                return "", None, None
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            audit = payload.get("audit") if isinstance(payload, dict) else None
            if not isinstance(audit, dict):
                return "", None, None
            risk_level = str(audit.get("risk_level") or "").strip()
            overall_pass = audit.get("overall_pass")
            entity_identity = audit.get("entity_identity")
            uncertain = entity_identity.get("uncertain") if isinstance(entity_identity, dict) else None
            return risk_level, overall_pass, uncertain
        except Exception:
            return "", None, None

    def _resolve_spotlight_copy(name: str) -> Tuple[str, str]:
        spot = spotlight_items.get(name)
        quote = ""
        review = ""
        if isinstance(spot, dict):
            quote = _pick_quote(spot)
            review = _clean_review_text(str(spot.get("review") or ""))
        if name == "武则天" and not review:
            review = "千秋功过，后人评说。"
        return quote, review

    def _resolve_birth_context(
        *,
        name: str,
        html_entry: Optional[HtmlEntry],
        dynasty: str,
        birthplace_raw: str,
        birthplace_ancient: str,
        birthplace_modern: str,
        coords_table: Dict[str, Tuple[float, float]],
    ) -> Dict[str, object]:
        nonlocal geocode_used
        birth_lat = None
        birth_lng = None
        html_birth_lat = None
        html_birth_lng = None
        pending_amap_query = ""
        pending_foreign_query = ""

        resolved_dynasty = dynasty
        resolved_birthplace_raw = birthplace_raw
        resolved_birthplace_ancient = birthplace_ancient
        resolved_birthplace_modern = birthplace_modern

        if html_entry:
            lat, lng, birthplace_text, dynasty_hint = _extract_birth_from_story_map_html(story_map_dir / html_entry.file)
            if lat is not None and lng is not None:
                html_birth_lat = float(lat)
                html_birth_lng = float(lng)
            if not resolved_dynasty and dynasty_hint:
                resolved_dynasty = dynasty_hint
            if not resolved_birthplace_raw and birthplace_text:
                resolved_birthplace_raw, resolved_birthplace_ancient, resolved_birthplace_modern = _extract_birthplace_from_md(
                    f"**出生**：{birthplace_text}"
                )

        lookup_terms = _birthplace_lookup_terms(
            resolved_birthplace_modern,
            resolved_birthplace_ancient,
            resolved_birthplace_raw,
        )

        if (birth_lat is None or birth_lng is None) and coords_table and lookup_terms:
            picked = _lookup_birth_coord_from_coords_table(
                coords_table,
                resolved_birthplace_modern,
                resolved_birthplace_ancient,
                resolved_birthplace_raw,
            )
            if picked:
                birth_lat = float(picked[0])
                birth_lng = float(picked[1])

        if (birth_lat is None or birth_lng is None) and hist_index and lookup_terms:
            coord0 = _lookup_birth_coord_from_hist_index(
                resolved_birthplace_modern,
                resolved_birthplace_ancient,
                resolved_birthplace_raw,
            )
            if coord0:
                birth_lat = float(coord0[0])
                birth_lng = float(coord0[1])

        if birth_lat is None or birth_lng is None:
            cached_birth = person_birth_coords.get(name)
            if cached_birth and isinstance(cached_birth, tuple) and len(cached_birth) >= 2 and lookup_terms:
                try:
                    birth_lat = float(cached_birth[0])
                    birth_lng = float(cached_birth[1])
                except Exception:
                    birth_lat = None
                    birth_lng = None

        if birth_lat is None or birth_lng is None:
            if html_birth_lat is not None and html_birth_lng is not None and lookup_terms:
                birth_lat = html_birth_lat
                birth_lng = html_birth_lng

        if birth_lat is None or birth_lng is None:
            q = _make_geocode_query(resolved_birthplace_modern, resolved_birthplace_ancient, resolved_birthplace_raw)
            if amap_key and _looks_like_geocode_query(q):
                pending_amap_query = q
            if _looks_like_foreign_geocode_query(q):
                pending_foreign_query = q

        if geocode_city and geocode_used < geocode_limit and (birth_lat is None or birth_lng is None):
            q = _finalize_geocode_query(
                resolved_birthplace_modern or resolved_birthplace_ancient or resolved_birthplace_raw or "",
                extra_prefix_pattern=r"^(?:祖籍|籍贯|故里|家乡|古称|传说中|传说人物)[:：\\s]*",
                split_markers=r"传说|小说|虚构|待查证|无考|不详",
            )
            if q and re.search(r"(世纪|年间|年|月|日|号|时期|当时|属|人物|传说|小说)", q) and not re.search(
                r"(省|市|县|区|州|郡|国|府|镇|乡|村|旗|盟|自治区|直辖|特区|都|城|岛|港|湾)",
                q,
            ):
                q = ""
            if q and (not (_looks_like_geocode_query(q) or _looks_like_foreign_geocode_query(q))):
                q = ""
            if q:
                try:
                    coord = geocode_city(q)
                except Exception:
                    coord = None
                if coord and isinstance(coord, tuple) and len(coord) >= 2:
                    birth_lat = float(coord[0])
                    birth_lng = float(coord[1])
                    geocode_used += 1

        if birth_lat is not None and birth_lng is not None:
            _set_person_birth_coord(name, birth_lat, birth_lng)
        elif not lookup_terms:
            _clear_person_birth_coord(name)

        return {
            "dynasty": resolved_dynasty,
            "birthplace_raw": resolved_birthplace_raw,
            "birthplace_ancient": resolved_birthplace_ancient,
            "birthplace_modern": resolved_birthplace_modern,
            "birth_lat": birth_lat,
            "birth_lng": birth_lng,
            "pending_amap_query": pending_amap_query,
            "pending_foreign_query": pending_foreign_query,
        }

    def _compute_time_year(dynasty: str, birth_year: Optional[int], death_year: Optional[int]) -> Optional[int]:
        by = birth_year if isinstance(birth_year, int) else None
        dy = death_year if isinstance(death_year, int) else None
        if by is not None and dy is not None:
            a0 = min(by, dy)
            b0 = max(by, dy)
            year_range = _dynasty_range_from_label(dynasty) or _dynasty_range_from_label(_pick_main_dynasty_by_years(by, dy))
            if year_range:
                a = max(a0, int(year_range[0]))
                b = min(b0, int(year_range[1]))
                if a < b:
                    return int(round((a + b) / 2))
            return int(round((a0 + b0) / 2))
        time_year = by if by is not None else dy
        if time_year is None and dynasty:
            return _dynasty_mid_year(dynasty)
        return time_year

    def _register_pending_birth_queries(node_idx: int, pending_amap_query: str, pending_foreign_query: str) -> None:
        if pending_amap_query:
            pending_amap[node_idx] = pending_amap_query
        if pending_foreign_query:
            pending_foreign[node_idx] = pending_foreign_query

    def _build_person_node(
        *,
        name: str,
        birth_year: Optional[int],
        death_year: Optional[int],
        dynasty: str,
        quote: str,
        review: str,
        aliases: List[str],
        foreign_name: str,
        domain_tags: List[str],
        main_role_band: str,
        main_role_label: str,
        audit_risk_level: str,
        audit_overall_pass: object,
        audit_uncertain: object,
        birthplace_ancient: str,
        birthplace_raw: str,
        birthplace_modern: str,
        native_place_ancient: str,
        native_place_raw: str,
        native_place_modern: str,
        birth_lat: object,
        birth_lng: object,
        html_entry: Optional[HtmlEntry],
        has_story: bool,
        relations: List[str],
        relations_meta: List[Dict[str, str]],
        search_fields: Dict[str, object],
        works: List[str],
        work_summaries: Dict[str, Dict[str, Any]],
        is_foreign: bool,
    ) -> Dict[str, object]:
        return {
            "person": name,
            "birth_year": birth_year,
            "death_year": death_year,
            "time_year": _compute_time_year(dynasty, birth_year, death_year),
            "dynasty": dynasty,
            "quote": quote,
            "review": review,
            "aliases": aliases,
            "foreign_name": foreign_name,
            "domain_tags": domain_tags,
            "main_role_band": main_role_band,
            "main_role_label": main_role_label,
            "risk_level": audit_risk_level,
            "audit_pass": audit_overall_pass,
            "audit_uncertain": audit_uncertain,
            "birthplace": birthplace_ancient,
            "birthplace_raw": birthplace_raw,
            "birthplace_modern": birthplace_modern,
            "native_place": native_place_ancient,
            "native_place_raw": native_place_raw,
            "native_place_modern": native_place_modern,
            "birth_lat_wgs84": birth_lat,
            "birth_lng_wgs84": birth_lng,
            "birth_lat": birth_lat,
            "birth_lng": birth_lng,
            "birth_coord_system": "WGS84" if birth_lat is not None and birth_lng is not None else "",
            "file": html_entry.file if html_entry else "",
            "has_story": has_story,
            "seed": _sha1_int(name),
            "relations": relations,
            "relations_meta": relations_meta,
            "search_keys": search_fields.get("search_keys", []),
            "search_tokens": search_fields.get("search_tokens", []),
            "search_pinyin": search_fields.get("search_pinyin", []),
            "works": works,
            "work_summaries": work_summaries,
            "is_foreign": bool(is_foreign),
        }

    nodes: List[Dict[str, Any]] = []
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    pending_amap: Dict[int, str] = {}
    pending_foreign: Dict[int, str] = {}
    for name, source_name, redirect_aliases in story_name_entries:
        md_path = story_md_dir / f"{source_name}.md"
        has_story = md_path.exists()
        md_text = ""
        birth_year = None
        death_year = None
        dynasty = ""
        relations: List[str] = []
        relations_meta: List[Dict[str, str]] = []
        aliases: List[str] = []
        foreign_name = ""
        domain_tags: List[str] = []
        birthplace_raw = ""
        birthplace_ancient = ""
        birthplace_modern = ""
        native_place_raw = ""
        native_place_ancient = ""
        native_place_modern = ""
        coords_table: Dict[str, Tuple[float, float]] = {}
        works: List[str] = []
        work_summaries: Dict[str, Dict[str, Any]] = {}
        if has_story:
            md_text = md_path.read_text(encoding="utf-8")
            birth_year, death_year = _extract_years_from_md(md_text)
            dynasty = _dynasty_hint_from_md(md_text)
            relations, relations_meta = _extract_relations(md_text)
            aliases, foreign_name, domain_tags = _extract_disambiguation(md_text)
            birthplace_raw, birthplace_ancient, birthplace_modern = _extract_birthplace_from_md(md_text)
            native_place_raw, native_place_ancient, native_place_modern = _extract_basic_place_from_md(
                md_text,
                ("籍贯", "祖籍"),
            )
            coords_table = _parse_coords_table_from_md(md_text)
        audit_risk_level, audit_overall_pass, audit_uncertain = _load_person_audit(name)
        if birth_year is not None:
            min_year = birth_year if min_year is None else min(min_year, birth_year)
            max_year = birth_year if max_year is None else max(max_year, birth_year)
        if death_year is not None:
            min_year = death_year if min_year is None else min(min_year, death_year)
            max_year = death_year if max_year is None else max(max_year, death_year)

        html_entry = latest_html.get(name) or latest_html.get(source_name)
        quote, review = _resolve_spotlight_copy(name)
        works = _resolve_person_works(spotlight_items.get(name), md_text)
        work_summaries = _pick_person_work_summaries(works, work_summary_items)
        main_role_band, main_role_label = _resolve_main_role_band(
            md_text=md_text,
            domain_tags=domain_tags,
            review=review,
            quote=quote,
        )
        birth_context = _resolve_birth_context(
            name=name,
            html_entry=html_entry,
            dynasty=dynasty,
            birthplace_raw=birthplace_raw,
            birthplace_ancient=birthplace_ancient,
            birthplace_modern=birthplace_modern,
            coords_table=coords_table,
        )
        dynasty = str(birth_context["dynasty"] or "")
        birthplace_raw = str(birth_context["birthplace_raw"] or "")
        birthplace_ancient = str(birth_context["birthplace_ancient"] or "")
        birthplace_modern = str(birth_context["birthplace_modern"] or "")
        birth_lat = birth_context.get("birth_lat")
        birth_lng = birth_context.get("birth_lng")
        pending_amap_query = str(birth_context.get("pending_amap_query") or "")
        pending_foreign_query = str(birth_context.get("pending_foreign_query") or "")
        preferred_birth_coord = None
        lookup_terms = _birthplace_lookup_terms(birthplace_modern, birthplace_ancient, birthplace_raw)
        if coords_table and lookup_terms:
            preferred_birth_coord = _lookup_birth_coord_from_coords_table(
                coords_table,
                birthplace_modern,
                birthplace_ancient,
                birthplace_raw,
            )
        if preferred_birth_coord:
            birth_lat = float(preferred_birth_coord[0])
            birth_lng = float(preferred_birth_coord[1])
            pending_amap_query = ""
            pending_foreign_query = ""
            _set_person_birth_coord(name, birth_lat, birth_lng)
        elif not lookup_terms:
            birth_lat = None
            birth_lng = None
            pending_amap_query = ""
            pending_foreign_query = ""
            _clear_person_birth_coord(name)
        node_idx = len(nodes)
        _register_pending_birth_queries(node_idx, pending_amap_query, pending_foreign_query)
        aliases = [str(x).strip() for x in aliases if str(x).strip()]
        for alias_name in redirect_aliases:
            if alias_name not in aliases and alias_name != name:
                aliases.append(alias_name)
        search_fields = build_search_fields(name, aliases, foreign_name)
        dynasty = _normalize_dynasty_label(person=name, dynasty_raw=dynasty, birth_year=birth_year, death_year=death_year)
        is_foreign = _is_foreign_person(
            foreign_name=foreign_name,
            birthplace_modern=birthplace_modern,
            birthplace_raw=birthplace_raw,
            dynasty=dynasty,
        )
        nodes.append(
            _build_person_node(
                name=name,
                birth_year=birth_year,
                death_year=death_year,
                dynasty=dynasty,
                quote=quote,
                review=review,
                aliases=aliases,
                foreign_name=foreign_name,
                domain_tags=domain_tags,
                main_role_band=main_role_band,
                main_role_label=main_role_label,
                audit_risk_level=audit_risk_level,
                audit_overall_pass=audit_overall_pass,
                audit_uncertain=audit_uncertain,
                birthplace_ancient=birthplace_ancient,
                birthplace_raw=birthplace_raw,
                birthplace_modern=birthplace_modern,
                native_place_ancient=native_place_ancient,
                native_place_raw=native_place_raw,
                native_place_modern=native_place_modern,
                birth_lat=birth_lat,
                birth_lng=birth_lng,
                html_entry=html_entry,
                has_story=has_story,
                relations=relations,
                relations_meta=relations_meta,
                search_fields=search_fields,
                works=works,
                work_summaries=work_summaries,
                is_foreign=is_foreign,
            )
        )

    if amap_key and pending_amap:
        _amap_geocode_batch(list(pending_amap.values()))
        for idx, q in pending_amap.items():
            if idx < 0 or idx >= len(nodes):
                continue
            coord = amap_cache.get(q)
            if coord and isinstance(coord, tuple) and len(coord) >= 2:
                try:
                    lat_g = float(coord[0])
                    lng_g = float(coord[1])
                except Exception:
                    continue
                lat_w, lng_w = _gcj02_to_wgs84(lat_g, lng_g)
                nodes[idx]["birth_lat_wgs84"] = float(lat_w)
                nodes[idx]["birth_lng_wgs84"] = float(lng_w)
                nodes[idx]["birth_lat"] = float(lat_w)
                nodes[idx]["birth_lng"] = float(lng_w)
                try:
                    _set_person_birth_coord(str(nodes[idx].get("person") or ""), float(lat_w), float(lng_w))
                except Exception:
                    pass
    if pending_foreign:
        _foreign_geocode_batch(list(pending_foreign.values()))
        for idx, q in pending_foreign.items():
            if idx < 0 or idx >= len(nodes):
                continue
            coord = foreign_cache.get(q)
            if coord and isinstance(coord, tuple) and len(coord) >= 2:
                try:
                    lat_w = float(coord[0])
                    lng_w = float(coord[1])
                except Exception:
                    continue
                nodes[idx]["birth_lat_wgs84"] = float(lat_w)
                nodes[idx]["birth_lng_wgs84"] = float(lng_w)
                nodes[idx]["birth_lat"] = float(lat_w)
                nodes[idx]["birth_lng"] = float(lng_w)
                try:
                    _set_person_birth_coord(str(nodes[idx].get("person") or ""), float(lat_w), float(lng_w))
                except Exception:
                    pass

    person_to_idx: Dict[str, int] = {}
    for i, node in enumerate(nodes):
        person_name = str(node.get("person") or "").strip()
        if person_name and person_name not in person_to_idx:
            person_to_idx[person_name] = i
        for alias_name in node.get("aliases") if isinstance(node.get("aliases"), list) else []:
            alias_text = str(alias_name or "").strip()
            if alias_text and alias_text not in person_to_idx:
                person_to_idx[alias_text] = i
    edges: List[Dict[str, Any]] = []
    kg_edges: List[Dict[str, int]] = []

    max_edges = 2200
    edge_set: Dict[Tuple[int, int], int] = {}

    def add_edge(i: int, j: int, meta: Optional[Dict[str, Any]] = None) -> None:
        nonlocal edges
        if i == j:
            return
        a, b = (i, j) if i < j else (j, i)
        key = (a, b)
        if key in edge_set:
            idx = edge_set[key]
            cur = edges[idx] if 0 <= idx < len(edges) else None
            if isinstance(cur, dict) and isinstance(meta, dict):
                try:
                    cc = float(cur.get("confidence"))
                except Exception:
                    cc = 0.0
                try:
                    nc = float(meta.get("confidence"))
                except Exception:
                    nc = 0.0
                if nc > cc:
                    cur.update(meta)
            return
        edge_set[key] = len(edges)
        e: Dict[str, Any] = {"a": a, "b": b}
        if isinstance(meta, dict):
            e.update(meta)
        edges.append(e)

    for i, n in enumerate(nodes):
        rels_meta = n.get("relations_meta") if isinstance(n.get("relations_meta"), list) else []
        if rels_meta:
            for r in rels_meta:
                if not isinstance(r, dict):
                    continue
                nm = str(r.get("name") or "").strip()
                if not nm:
                    continue
                j = person_to_idx.get(nm)
                if j is None or j == i:
                    continue
                label = str(r.get("label") or "亲友").strip() or "亲友"
                add_edge(i, j, {"type": "bio", "label": label, "confidence": 0.55})
                if len(edges) >= max_edges:
                    break
        else:
            rels = n.get("relations") if isinstance(n.get("relations"), list) else []
            for r in rels:
                j = person_to_idx.get(r)
                if j is None or j == i:
                    continue
                add_edge(i, j, {"type": "bio", "label": "文本提及", "confidence": 0.55})
                if len(edges) >= max_edges:
                    break
        if len(edges) >= max_edges:
            break

    try:
        kg = _read_json(KNOWLEDGE_GRAPH_JSON)
        raw_edges = kg.get("edges") if isinstance(kg, dict) else None
        if isinstance(raw_edges, list):
            for e in raw_edges:
                if not isinstance(e, dict):
                    continue
                typ = str(e.get("type") or "").strip().lower()
                w = e.get("weight")
                try:
                    if int(w or 0) < 2:
                        continue
                except Exception:
                    continue
                if typ not in {"same_book", "manual"}:
                    continue
                a = str(e.get("source") or "").strip()
                b = str(e.get("target") or "").strip()
                ia = person_to_idx.get(a)
                ib = person_to_idx.get(b)
                if ia is None or ib is None or ia == ib:
                    continue
                if typ == "same_book":
                    continue
                conf = None
                try:
                    conf = float(e.get("relation_confidence"))
                except Exception:
                    conf = None
                if conf is None or not (0.0 <= conf <= 1.0):
                    try:
                        ww = int(w or 0)
                    except Exception:
                        ww = 0
                    if typ == "same_book":
                        conf = max(0.15, min(0.60, 0.15 + 0.07 * max(0, ww - 2)))
                    else:
                        conf = 0.90
                label = str(e.get("relation_label") or "").strip()
                if not label:
                    if typ == "same_book":
                        da = str(nodes[ia].get("dynasty") or "").strip()
                        db = str(nodes[ib].get("dynasty") or "").strip()
                        if da and db and da[:2] == db[:2]:
                            label = "同朝共现"
                            conf = min(1.0, float(conf) + 0.10)
                        else:
                            ta = nodes[ia].get("domain_tags") if isinstance(nodes[ia].get("domain_tags"), list) else []
                            tb = nodes[ib].get("domain_tags") if isinstance(nodes[ib].get("domain_tags"), list) else []
                            sa = {str(x).strip() for x in ta if str(x).strip()}
                            sb = {str(x).strip() for x in tb if str(x).strip()}
                            if sa and sb and (sa & sb):
                                label = "同领域共现"
                                conf = min(1.0, float(conf) + 0.08)
                            else:
                                label = "同册共现"
                    else:
                        label = "人工关系"
                add_edge(ia, ib, {"type": typ, "label": label, "confidence": float(conf), "weight": int(w or 0)})
                if len(edges) >= max_edges:
                    break
    except Exception:
        kg_edges = []

    payload = _prepare_home_payload_for_output(
        {
            "min_year": MIN_YEAR,
            "max_year": MAX_YEAR,
            "nodes": nodes,
            "edges": edges,
            "kg_edges": kg_edges,
        },
        default_start=int(args.default_start),
        default_end=int(args.default_end),
    )
    try:
        amap_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload_cache: Dict[str, Any] = {}
        for k, v in amap_cache.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if v is None:
                payload_cache[k] = None
            else:
                payload_cache[k] = [float(v[0]), float(v[1])]
        amap_cache_path.write_text(json.dumps(payload_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        foreign_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload_cache2: Dict[str, Any] = {}
        for k, v in foreign_cache.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if v is None:
                payload_cache2[k] = None
            else:
                payload_cache2[k] = [float(v[0]), float(v[1])]
        foreign_cache_path.write_text(json.dumps(payload_cache2, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        if person_birth_coords_dirty > 0:
            BIRTH_COORDS_WGS84_JSON.parent.mkdir(parents=True, exist_ok=True)
            payload_pbc: Dict[str, Any] = {}
            for k in sorted(person_birth_coords.keys()):
                v = person_birth_coords.get(k)
                if not v:
                    continue
                payload_pbc[k] = [float(v[0]), float(v[1])]
            BIRTH_COORDS_WGS84_JSON.write_text(json.dumps(payload_pbc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    outputs = _write_homepage_outputs(
        story_map_dir=story_map_dir,
        out_index_name=str(args.out_index),
        out_data_name=str(args.out_data),
        title=str(args.title),
        payload=payload,
        active_redirects=active_redirects,
        sync_payload_to_neo4j=True,
    )
    print(json.dumps({"ok": True, **outputs, "source": "build"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
