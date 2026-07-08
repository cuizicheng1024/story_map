#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen

from storymap.script.core.build_meta import build_artifact_meta
from storymap.script.core.person_registry import (
    canonical_story_name_entries as registry_canonical_story_name_entries,
    person_redirects,
)
from storymap.script.core.project_paths import data_corpus_file_path

from tools.build.homepage.config import (
    BIRTH_COORDS_WGS84_JSON,
    DATA_REPORTS_DIR,
    GRAPH_ARTIFACT_DIR,
    HOME_DETAIL_NODE_FIELDS,
    HOMEPAGE_PET_ASSET_CANDIDATES,
    HOMEPAGE_PET_ASSET_OUTPUT_NAME,
    KNOWLEDGE_GRAPH_JSON,
    MAX_YEAR,
    MIN_YEAR,
    REPO_ROOT,
    STORY_MAP_DIR,
    STORY_MD_DIR,
    SUMMARY_INDEX_JSON,
    WORK_SUMMARY_INDEX_JSON,
    apply_story_map_env_aliases,
    graph_backend_name,
    load_home_graph_payload_with_source,
    should_sync_to_neo4j,
    sync_graph_payload_to_neo4j,
    write_normalized_graph_json,
)
from tools.build.homepage import loaders as _loaders
from tools.build.homepage import normalizers as _normalizers
from tools.build.homepage.rendering import _analytics_head_html, _design_tokens_style_tag, _render_index_html, _runtime_api_base_env
from tools.build.homepage.assets import _sync_embedded_apps, _sync_homepage_pet_asset
from tools.build.homepage.assets import _sync_vendor_assets as _assets_sync_vendor_assets


def _sync_vendor_assets(story_map_dir: Path) -> None:
    import shutil
    src = REPO_ROOT / "vendor"
    if not src.is_dir():
        return
    shutil.copytree(src, story_map_dir / "vendor", dirs_exist_ok=True)
from tools.build.homepage.indexes import _derive_home_detail_file_name


# 首页“空间视角”以中国读者常用出生/成长地点展示。
# 李白出生地存在“碎叶城/蜀中青莲乡”两说；高德会把“碎叶城”误解析到广东，
# 因此这里固定到四川江油青莲一带，避免空间视角出现明显错误。
PERSON_BIRTH_COORD_OVERRIDES_WGS84: Dict[str, Tuple[float, float]] = {
    "李白": (31.778, 104.744),
    "列子": (34.7466, 113.6254),
    "高适": (34.4143, 115.6564),
}
from tools.build.homepage_search import HAS_PINYIN, build_search_fields

globals().update({k: v for k, v in vars(_normalizers).items() if k.startswith("_")})
globals().update({k: v for k, v in vars(_loaders).items() if k.startswith("_") or k == "HtmlEntry"})


def _canonical_story_name_entries(raw_names: List[str]) -> List[Tuple[str, str, List[str]]]:
    return registry_canonical_story_name_entries(raw_names)


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


def _prepare_home_payload_for_output(base_payload: Dict[str, Any], *, default_start: int, default_end: int) -> Dict[str, Any]:
    from tools.build.homepage.indexes import _prepare_home_payload_for_output as impl
    original = impl.__globals__["_build_payload_meta"]
    impl.__globals__["_build_payload_meta"] = _build_payload_meta
    try:
        return impl(base_payload, default_start=default_start, default_end=default_end)
    finally:
        impl.__globals__["_build_payload_meta"] = original


def _split_home_payload_for_delivery(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from tools.build.homepage.indexes import _split_home_payload_for_delivery as impl
    original = impl.__globals__["_build_payload_meta"]
    impl.__globals__["_build_payload_meta"] = _build_payload_meta
    try:
        return impl(payload)
    finally:
        impl.__globals__["_build_payload_meta"] = original


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
        from storymap.script.map.map_client import geocode_city as _geocode_city

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
        override_birth_coord = PERSON_BIRTH_COORD_OVERRIDES_WGS84.get(name)
        if override_birth_coord:
            birth_lat = float(override_birth_coord[0])
            birth_lng = float(override_birth_coord[1])
            pending_amap_query = ""
            pending_foreign_query = ""
            _set_person_birth_coord(name, birth_lat, birth_lng)
        elif preferred_birth_coord:
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
