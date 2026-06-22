"""
map_client
职责：与地图与地理计算相关的通用能力层，供 story_map 集成调用。
- 地理编码：优先通过高德 WebService（GCJ-02），拿到结果后统一转换为 WGS84；失败回退 OSM（原生 WGS84）；国外地名再兜底百科坐标接口
- 距离计算：本地 Haversine
- 地图渲染：由本地 HTML 渲染模块生成页面
"""
import math
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.request import urlopen

from ..core.env_utils import load_project_env
from . import coords_markdown as coords_markdown_utils
from . import geocode_candidates as geocode_candidate_utils
from . import geocode_config as geocode_config_utils
from . import geocode_http as geocode_http_utils
from . import geocode_provider_bridge as geocode_provider_bridge_utils
from . import geocode_providers as geocode_provider_utils
from . import geocode_runtime_state as geocode_runtime_state_utils


_DEFAULT_USER_AGENT = "map-story/1.0"
_LOGGER = logging.getLogger("map_client")
if not _LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)

_GEOCODE_CACHE: Dict[str, Tuple[float, float]] = {}
_GEOCODE_CACHE_LOCK = threading.Lock()
_GEOCODE_CACHE_PATH: Optional[str] = None
_GEOCODE_CACHE_LAST_SAVE_TS = 0.0
_GEOCODE_NEGATIVE_CACHE: Dict[str, Dict[str, object]] = {}
_GEOCODE_NEGATIVE_CACHE_LOCK = threading.Lock()
_GEOCODE_NEGATIVE_CACHE_PATH: Optional[str] = None
_GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS = 0.0
_GEOCODE_METRICS: Dict[str, int] = {
    "lookups": 0,
    "cache_hits": 0,
    "negative_cache_hits": 0,
    "misses": 0,
    "successes": 0,
    "failures": 0,
    "timeouts": 0,
    "amap_requests": 0,
    "amap_successes": 0,
    "amap_failures": 0,
    "monid_requests": 0,
    "monid_successes": 0,
    "monid_failures": 0,
    "nominatim_requests": 0,
    "nominatim_successes": 0,
    "nominatim_failures": 0,
    "wikidata_requests": 0,
    "wikidata_successes": 0,
    "wikidata_failures": 0,
}
_GEOCODE_METRICS_LOCK = threading.Lock()
_GEOCODE_HTTP_SEM = threading.Semaphore(geocode_config_utils.env_int("MAP_STORY_GEOCODE_HTTP_CONCURRENCY", 2))
_GEOCODE_RL_LOCK = threading.Lock()
_GEOCODE_LAST_REQ_TS = 0.0
_AMAP_RL_LOCK = threading.Lock()
_AMAP_LAST_REQ_TS = 0.0


def _set_geocode_last_request_ts(value: float) -> None:
    global _GEOCODE_LAST_REQ_TS
    _GEOCODE_LAST_REQ_TS = float(value)


def _set_amap_last_request_ts(value: float) -> None:
    global _AMAP_LAST_REQ_TS
    _AMAP_LAST_REQ_TS = float(value)


def _geocode_rate_limit() -> None:
    geocode_http_utils.rate_limit(
        lock=_GEOCODE_RL_LOCK,
        get_last_request_ts=lambda: _GEOCODE_LAST_REQ_TS,
        set_last_request_ts=_set_geocode_last_request_ts,
        min_interval=geocode_config_utils.geocode_min_interval_seconds(),
    )


def _resolve_geocode_cache_path() -> Optional[str]:
    env = (os.getenv("MAP_STORY_GEOCODE_CACHE") or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    root = _project_root()
    return os.path.join(root, ".cache", "map_story_geocode_cache.json")


def _resolve_geocode_negative_cache_path() -> Optional[str]:
    env = (os.getenv("MAP_STORY_GEOCODE_NEGATIVE_CACHE") or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    root = _project_root()
    return os.path.join(root, ".cache", "map_story_geocode_negative_cache.json")


def _geocode_negative_cache_ttl() -> int:
    return geocode_config_utils.geocode_negative_cache_ttl()


def _fetch_timeout_seconds() -> int:
    return geocode_config_utils.fetch_timeout_seconds()


def _nominatim_timeout_seconds() -> int:
    return geocode_config_utils.nominatim_timeout_seconds()


def _amap_timeout_seconds() -> int:
    return geocode_config_utils.amap_timeout_seconds()


def _monid_timeout_seconds() -> int:
    return geocode_config_utils.monid_timeout_seconds()


def _monid_api_key() -> str:
    return geocode_config_utils.monid_api_key()


def _monid_geocode_enabled() -> bool:
    return geocode_config_utils.monid_geocode_enabled()


def _record_geocode_metric(key: str, amount: int = 1) -> None:
    with _GEOCODE_METRICS_LOCK:
        geocode_runtime_state_utils.record_metric(_GEOCODE_METRICS, key, amount)


def geocode_metrics_snapshot() -> Dict[str, object]:
    with _GEOCODE_METRICS_LOCK:
        metrics = dict(_GEOCODE_METRICS)
    return geocode_runtime_state_utils.build_metrics_snapshot(
        metrics,
        negative_cache_size=_geocode_negative_cache_size(),
    )


def _reset_geocode_runtime_state() -> None:
    with _GEOCODE_CACHE_LOCK:
        _GEOCODE_CACHE.clear()
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        with _GEOCODE_METRICS_LOCK:
            geocode_runtime_state_utils.reset_runtime_state(_GEOCODE_NEGATIVE_CACHE, _GEOCODE_METRICS)


def _prune_geocode_negative_cache(*, now: Optional[float] = None) -> bool:
    current = float(now if now is not None else time.time())
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        return geocode_runtime_state_utils.prune_negative_cache(_GEOCODE_NEGATIVE_CACHE, now=current)


def _geocode_negative_cache_size() -> int:
    _prune_geocode_negative_cache()
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        return len(_GEOCODE_NEGATIVE_CACHE)


def _geocode_negative_cache_get(name: str) -> Optional[Dict[str, object]]:
    key = str(name or "").strip()
    if not key:
        return None
    _prune_geocode_negative_cache()
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        return geocode_runtime_state_utils.negative_cache_get(_GEOCODE_NEGATIVE_CACHE, key)


def _geocode_negative_cache_set(name: str, *, reason: str) -> None:
    key = str(name or "").strip()
    if not key:
        return
    ttl = _geocode_negative_cache_ttl()
    now = time.time()
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        geocode_runtime_state_utils.negative_cache_set(
            _GEOCODE_NEGATIVE_CACHE,
            key,
            reason=reason,
            ttl_seconds=ttl,
            now=now,
        )
    _save_geocode_negative_cache(force=False)


def _geocode_negative_cache_clear(*names: str) -> None:
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        changed = geocode_runtime_state_utils.negative_cache_clear(_GEOCODE_NEGATIVE_CACHE, *names)
    if changed:
        _save_geocode_negative_cache(force=False)


def _load_geocode_cache() -> None:
    global _GEOCODE_CACHE_PATH
    _GEOCODE_CACHE_PATH = _resolve_geocode_cache_path()
    p = _GEOCODE_CACHE_PATH
    try:
        loaded = geocode_runtime_state_utils.load_coord_cache(p or "", is_valid_coord=_is_valid_coord)
    except Exception:
        return
    if not loaded:
        return
    with _GEOCODE_CACHE_LOCK:
        _GEOCODE_CACHE.clear()
        _GEOCODE_CACHE.update(loaded)


def _load_geocode_negative_cache() -> None:
    global _GEOCODE_NEGATIVE_CACHE_PATH
    _GEOCODE_NEGATIVE_CACHE_PATH = _resolve_geocode_negative_cache_path()
    p = _GEOCODE_NEGATIVE_CACHE_PATH
    now = time.time()
    loaded = geocode_runtime_state_utils.load_negative_cache(p or "", now=now)
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        _GEOCODE_NEGATIVE_CACHE.clear()
        _GEOCODE_NEGATIVE_CACHE.update(loaded)


def _save_geocode_cache(force: bool = False) -> None:
    global _GEOCODE_CACHE_LAST_SAVE_TS
    p = _GEOCODE_CACHE_PATH or _resolve_geocode_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _GEOCODE_CACHE_LAST_SAVE_TS < 2.0):
        return
    with _GEOCODE_CACHE_LOCK:
        saved = geocode_runtime_state_utils.save_coord_cache(p, _GEOCODE_CACHE)
    if saved:
        _GEOCODE_CACHE_LAST_SAVE_TS = now


def _save_geocode_negative_cache(force: bool = False) -> None:
    global _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS
    p = _GEOCODE_NEGATIVE_CACHE_PATH or _resolve_geocode_negative_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS < 2.0):
        return
    _prune_geocode_negative_cache(now=now)
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        saved = geocode_runtime_state_utils.save_negative_cache(p, _GEOCODE_NEGATIVE_CACHE, now=now)
    if saved:
        _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS = now


def _geocode_cache_get(name: str) -> Optional[Tuple[float, float]]:
    with _GEOCODE_CACHE_LOCK:
        return geocode_runtime_state_utils.coord_cache_get(_GEOCODE_CACHE, name)


def _geocode_cache_set(name: str, coord: Tuple[float, float]) -> None:
    with _GEOCODE_CACHE_LOCK:
        updated = geocode_runtime_state_utils.coord_cache_set(_GEOCODE_CACHE, name, coord)
    if updated:
        _save_geocode_cache(force=False)

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


load_project_env(from_file=__file__, override=False)
_load_geocode_cache()
_load_geocode_negative_cache()


def _is_valid_coord(lat: object, lon: object) -> bool:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return False
    if abs(lat_f) > 90 or abs(lon_f) > 180:
        return False
    return True


def _is_inside_china(lat: object, lon: object) -> bool:
    if not _is_valid_coord(lat, lon):
        return False
    lat_f = float(lat)
    lon_f = float(lon)
    return 17.5 <= lat_f <= 55.5 and 72.0 <= lon_f <= 136.5


# ---------------------------------------------------------------------------
# Coordinate system conversion
# - AMap (Gaode) geocoding result is typically GCJ-02.
# - Leaflet + most public tiles are aligned to WGS84.
# We therefore normalize coordinates to WGS84 as early as possible.
# ---------------------------------------------------------------------------

_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def _gcj02_to_wgs84(lat: float, lon: float) -> Tuple[float, float]:
    """Convert GCJ-02 -> WGS84.

    Notes:
    - The conversion is only meaningful inside mainland China; outside China we return input.
    - This is the commonly used approximate inverse transform.
    """

    if not _is_inside_china(lat, lon):
        return lat, lon

    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)

    rad_lat = lat / 180.0 * _PI
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lat = (d_lat * 180.0) / (((_A * (1 - _EE)) / (magic * sqrt_magic)) * _PI)
    d_lon = (d_lon * 180.0) / ((_A / sqrt_magic) * math.cos(rad_lat) * _PI)

    mg_lat = lat + d_lat
    mg_lon = lon + d_lon

    return lat * 2.0 - mg_lat, lon * 2.0 - mg_lon


def _looks_chinese(text: str) -> bool:
    return geocode_candidate_utils.looks_chinese(text)


def _looks_foreign_location(text: str) -> bool:
    return geocode_candidate_utils.looks_foreign_location(text)


def _is_meaningful_place_candidate(text: str) -> bool:
    return geocode_candidate_utils.is_meaningful_place_candidate(text)


def _log_rejected_geocode_candidate(original: str, reason: str, cleaned: str) -> None:
    _LOGGER.info(
        "geocode_candidate_rejected reason=%s original=%s candidate=%s",
        reason,
        str(original or "").strip(),
        str(cleaned or "").strip(),
    )


def _build_geocode_candidates(name: str) -> List[str]:
    return geocode_candidate_utils.build_geocode_candidates(name, on_rejected=_log_rejected_geocode_candidate)


def _fetch_json(url: str, *, timeout: Optional[int] = None) -> Optional[object]:
    return geocode_provider_bridge_utils.fetch_json(
        url,
        user_agent=_DEFAULT_USER_AGENT,
        timeout_seconds=int(timeout or _fetch_timeout_seconds()),
        semaphore=_GEOCODE_HTTP_SEM,
        rate_limit_fn=_geocode_rate_limit,
        urlopen_fn=urlopen,
        record_timeout=lambda: _record_geocode_metric("timeouts"),
    )


def _post_json(
    url: str,
    payload: object,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> Optional[object]:
    return geocode_provider_bridge_utils.post_json(
        url,
        payload,
        user_agent=_DEFAULT_USER_AGENT,
        timeout_seconds=int(timeout or _fetch_timeout_seconds()),
        semaphore=_GEOCODE_HTTP_SEM,
        rate_limit_fn=_geocode_rate_limit,
        urlopen_fn=urlopen,
        record_timeout=lambda: _record_geocode_metric("timeouts"),
        headers=headers,
    )


def _monid_geocode(name: str) -> Optional[Tuple[float, float]]:
    return geocode_provider_bridge_utils.monid_geocode(
        name,
        api_key=_monid_api_key(),
        post_json_fn=_post_json,
        timeout_seconds=_monid_timeout_seconds(),
        record_metric=_record_geocode_metric,
        is_valid_coord=_is_valid_coord,
    )


def _geocode_wikidata(name: str) -> Optional[Tuple[float, float]]:
    return geocode_provider_bridge_utils.geocode_wikidata(
        name,
        fetch_json_fn=_fetch_json,
        quote_text=quote,
        record_metric=_record_geocode_metric,
        is_valid_coord=_is_valid_coord,
        is_meaningful_place_candidate=_is_meaningful_place_candidate,
    )


def _geocode_nominatim(name: str, force_cn: bool = False) -> Optional[Tuple[float, float]]:
    return geocode_provider_bridge_utils.geocode_nominatim(
        name,
        force_cn=force_cn,
        fetch_json_fn=_fetch_json,
        quote_text=quote,
        timeout_seconds=_nominatim_timeout_seconds(),
        record_metric=_record_geocode_metric,
        is_inside_china=_is_inside_china,
        mapsco_api_key=geocode_provider_utils.default_mapsco_api_key(),
    )


def _amap_rate_limit() -> None:
    geocode_http_utils.rate_limit(
        lock=_AMAP_RL_LOCK,
        get_last_request_ts=lambda: _AMAP_LAST_REQ_TS,
        set_last_request_ts=_set_amap_last_request_ts,
        min_interval=geocode_config_utils.amap_min_interval_seconds(),
    )


def _amap_webservice_geocode(address: str) -> Optional[Tuple[float, float]]:
    def _fetch_with_amap_rate_limit(url: str, *, timeout: Optional[int] = None) -> Optional[object]:
        return geocode_provider_bridge_utils.fetch_json(
            url,
            user_agent=_DEFAULT_USER_AGENT,
            timeout_seconds=int(timeout or _fetch_timeout_seconds()),
            semaphore=_GEOCODE_HTTP_SEM,
            rate_limit_fn=_amap_rate_limit,
            urlopen_fn=urlopen,
            record_timeout=lambda: _record_geocode_metric("timeouts"),
        )

    return geocode_provider_bridge_utils.amap_webservice_geocode(
        address,
        amap_key=geocode_provider_utils.default_amap_key(),
        fetch_json_fn=_fetch_with_amap_rate_limit,
        quote_text=quote,
        timeout_seconds=_amap_timeout_seconds(),
        record_metric=_record_geocode_metric,
        is_valid_coord=_is_valid_coord,
        gcj02_to_wgs84=_gcj02_to_wgs84,
    )


def geocode_city(name: str) -> Optional[Tuple[float, float]]:
    """城市/地址字符串 → WGS84 经纬度。

    - 若命中高德 WebService 地理编码（通常为 GCJ-02），则在落库/渲染前统一转换为 WGS84。
    - 若回退公共地理编码（OSM 系），则其结果本身即为 WGS84。
    """
    return geocode_provider_utils.resolve_city_geocode(
        name,
        build_candidates=_build_geocode_candidates,
        looks_chinese=_looks_chinese,
        looks_foreign_location=_looks_foreign_location,
        cache_get=_geocode_cache_get,
        cache_set=_geocode_cache_set,
        negative_cache_get=_geocode_negative_cache_get,
        negative_cache_set=lambda value: _geocode_negative_cache_set(value, reason="no_result"),
        negative_cache_clear=_geocode_negative_cache_clear,
        record_metric=_record_geocode_metric,
        amap_geocode=_amap_webservice_geocode,
        monid_geocode_enabled=_monid_geocode_enabled,
        monid_geocode=_monid_geocode,
        wikidata_geocode=_geocode_wikidata,
        nominatim_geocode=_geocode_nominatim,
    )


def extract_places_in_order(md: str) -> List[str]:
    return coords_markdown_utils.extract_places_in_order(md)


def append_coords_section(md: str) -> str:
    return coords_markdown_utils.append_coords_section(md, geocode_fn=geocode_city)


def compute_total_distance_km(md: str) -> Optional[float]:
    return coords_markdown_utils.compute_total_distance_km(md)


def insert_distance_intro(md: str, distance_km: float) -> str:
    return coords_markdown_utils.insert_distance_intro(md, distance_km)
