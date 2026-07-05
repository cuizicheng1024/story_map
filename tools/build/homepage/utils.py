"""首页构建工具函数 — 坐标变换、HTML扫描、元数据生成。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen

from storymap.script.core.project_paths import (
    data_corpus_file_path,
    data_corpus_dir_path,
    is_valid_person_name,
    person_name_from_filename,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
    story_person_names,
)
from storymap.script.core.analytics import analytics_head_html
from storymap.script.core.person_registry import canonical_story_name_entries as registry_canonical_story_name_entries, person_redirects
from storymap.script.profile.tooltip_js import person_tooltip_js

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
try:
    from storymap.script.core.env_utils import apply_story_map_env_aliases, env_flag
except Exception:
    apply_story_map_env_aliases = None
    env_flag = None

REPO_ROOT = project_root_path()
if load_dotenv:
    load_dotenv(dotenv_path=str((REPO_ROOT / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT.parent / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT / "data" / ".env").resolve()))
if apply_story_map_env_aliases:
    apply_story_map_env_aliases()

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
    return {
        "component": "stellar_homepage",
        "build_at": _now().replace(" ", "T"),
        "generated_at": _now().replace(" ", "T"),
    }


def _analytics_head_html() -> str:
    return analytics_head_html(page_type="homepage", page_name="人类群星闪耀时")


def _runtime_api_base_env() -> str:
    api_base = str(os.getenv("MAP_STORY_API_BASE", "")).strip()
    if "legacy.example" in api_base.lower():
        return ""
    # 同 renderer.py：避免把 127.0.0.1 / localhost 硬编码进静态页面，
    # 否则浏览器在公网域名下会把所有 fetch 走到用户本地的 8765，永远连不到真实后端。
    lowered = api_base.lower()
    if (lowered.startswith("http://127.0.0.1") or lowered.startswith("http://localhost")
            or lowered.startswith("https://localhost")
            or lowered.startswith("http://[::1]") or lowered.startswith("https://[::1]")):
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


_json_cache: Dict[str, Any] = {}


def _read_json(path: Path) -> Any:
    key = str(path.resolve())
    if key in _json_cache:
        return _json_cache[key]
    data = json.loads(path.read_text(encoding="utf-8"))
    _json_cache[key] = data
    return data


def _clear_json_cache() -> None:
    """Clear the JSON read cache (useful for testing or hot-reload)."""
    _json_cache.clear()




