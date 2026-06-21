"""
map_client
职责：与地图与地理计算相关的通用能力层，供 story_map 集成调用。
- 地理编码：优先通过高德 WebService（GCJ-02），拿到结果后统一转换为 WGS84；失败回退 OSM（原生 WGS84）；国外地名再兜底百科坐标接口
- 距离计算：本地 Haversine
- 地图渲染：由本地 HTML 渲染模块生成页面
"""
import json
import math
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from ..env_utils import load_project_env
except ImportError:
    from env_utils import load_project_env


_DEFAULT_USER_AGENT = "map-story/1.0"
_TABLE_SEPARATOR_RE = re.compile(r"^\|\s*-{3,}\s*\|")
_PAREN_CONTENT_RE = re.compile(r"[（(].*?[)）]")
_GEOCODE_ENDPOINTS = [
    ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q={}", "list"),
    ("https://geocode.maps.co/search?q={}", "list"),
    ("https://photon.komoot.io/api/?limit=1&q={}", "photon"),
]
_WIKIDATA_SEARCH_ENDPOINT = "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&type=item&limit=5&language={language}&uselang={language}&search={query}"
_WIKIDATA_ENTITY_ENDPOINT = "https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
_FOREIGN_LOCATION_MARKERS = (
    "吉尔吉斯斯坦", "巴基斯坦", "阿富汗", "澳大利亚", "新西兰", "阿根廷", "葡萄牙",
    "俄罗斯", "美国", "英国", "法国", "德国", "日本", "韩国", "朝鲜", "越南", "泰国",
    "缅甸", "老挝", "柬埔寨", "印度", "伊朗", "伊拉克", "土耳其", "埃及", "加拿大",
    "墨西哥", "巴西", "西班牙", "意大利", "荷兰", "比利时", "瑞士", "瑞典", "挪威",
    "芬兰", "丹麦", "爱尔兰", "以色列", "沙特", "阿联酋", "卡塔尔", "南非", "共和国",
    "王国", "联邦", "斯坦",
)

_LOGGER = logging.getLogger("map_client")
if not _LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)

_GEOCODE_REJECT_EXACT = {
    "-",
    "--",
    "—",
    "——",
    "未知",
    "不详",
    "无",
    "暂无",
    "地点",
    "位置",
    "地名",
    "某地",
    "当地",
    "此地",
    "这里",
    "那里",
    "去世",
    "出生",
    "出生地",
    "去世地",
    "逝世",
    "死亡",
    "中国",
    "全国",
    "世界",
    "海外",
    "国内",
    "各地",
    "中国去世",
    "中国出生",
}
_GEOCODE_PREFIX_RE = re.compile(
    r"^(?:出生于|生于|去世于|卒于|逝于|死于|位于|位在|今属|今为|今在|今称|今名为|古称|又称|旧称|别称|地点(?:为)?|位置(?:为)?|故里|故乡|籍贯|祖籍|原籍)\s*[:：]?\s*"
)
_GEOCODE_REJECT_PATTERNS = (
    re.compile(r"(?:待考|不详|未知|存疑|说法不一|一说|另说|传说|推测|可能|未详|无确切|缺乏确切|史载不详)"),
    re.compile(r"(?:具体|确切).{0,8}(?:位置|地点|地名)"),
    re.compile(r"(?:位置|地点|地名).{0,8}(?:不详|待考|存疑|未知|不明)"),
    re.compile(r"(?:出生|去世|逝世|卒|死亡)(?:地|于)?$"),
)
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
    "nominatim_requests": 0,
    "nominatim_successes": 0,
    "nominatim_failures": 0,
    "wikidata_requests": 0,
    "wikidata_successes": 0,
    "wikidata_failures": 0,
}
_GEOCODE_METRICS_LOCK = threading.Lock()
_GEOCODE_HTTP_SEM = threading.Semaphore(max(1, int(os.getenv("MAP_STORY_GEOCODE_HTTP_CONCURRENCY", "2"))))
_GEOCODE_RL_LOCK = threading.Lock()
_GEOCODE_LAST_REQ_TS = 0.0
_AMAP_RL_LOCK = threading.Lock()
_AMAP_LAST_REQ_TS = 0.0


def _geocode_rate_limit() -> None:
    min_interval = float(os.getenv("MAP_STORY_GEOCODE_MIN_INTERVAL", "1.1"))
    if min_interval <= 0:
        return
    global _GEOCODE_LAST_REQ_TS
    with _GEOCODE_RL_LOCK:
        now = time.monotonic()
        wait = (_GEOCODE_LAST_REQ_TS + min_interval) - now
        if wait > 0:
            time.sleep(wait)
        _GEOCODE_LAST_REQ_TS = time.monotonic()


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


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)) or str(default)))
    except Exception:
        return max(1, int(default))


def _geocode_negative_cache_ttl() -> int:
    return _env_int("MAP_STORY_GEOCODE_NEGATIVE_CACHE_TTL", 300)


def _fetch_timeout_seconds() -> int:
    return _env_int("MAP_STORY_GEOCODE_FETCH_TIMEOUT", 16)


def _nominatim_timeout_seconds() -> int:
    return _env_int("MAP_STORY_GEOCODE_NOMINATIM_TIMEOUT", _fetch_timeout_seconds())


def _amap_timeout_seconds() -> int:
    return _env_int("MAP_STORY_AMAP_TIMEOUT", 12)


def _record_geocode_metric(key: str, amount: int = 1) -> None:
    with _GEOCODE_METRICS_LOCK:
        _GEOCODE_METRICS[key] = int(_GEOCODE_METRICS.get(key, 0)) + int(amount)


def geocode_metrics_snapshot() -> Dict[str, object]:
    with _GEOCODE_METRICS_LOCK:
        metrics = {k: int(v) for k, v in _GEOCODE_METRICS.items()}
    lookups = max(1, metrics.get("lookups", 0))
    provider_requests = (
        metrics.get("amap_requests", 0)
        + metrics.get("nominatim_requests", 0)
        + metrics.get("wikidata_requests", 0)
    )
    return {
        **metrics,
        "cache_hit_rate": round(metrics.get("cache_hits", 0) / lookups, 4),
        "negative_cache_hit_rate": round(metrics.get("negative_cache_hits", 0) / lookups, 4),
        "success_rate": round(metrics.get("successes", 0) / lookups, 4),
        "timeout_rate": round(metrics.get("timeouts", 0) / max(1, provider_requests), 4),
        "negative_cache_size": _geocode_negative_cache_size(),
    }


def _reset_geocode_runtime_state() -> None:
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        _GEOCODE_NEGATIVE_CACHE.clear()
    with _GEOCODE_METRICS_LOCK:
        for key in list(_GEOCODE_METRICS.keys()):
            _GEOCODE_METRICS[key] = 0


def _prune_geocode_negative_cache(*, now: Optional[float] = None) -> bool:
    current = float(now if now is not None else time.time())
    removed = False
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        expired = [key for key, value in _GEOCODE_NEGATIVE_CACHE.items() if float(value.get("expires_at") or 0) <= current]
        for key in expired:
            _GEOCODE_NEGATIVE_CACHE.pop(key, None)
            removed = True
    return removed


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
        item = _GEOCODE_NEGATIVE_CACHE.get(key)
        if not isinstance(item, dict):
            return None
        return dict(item)


def _geocode_negative_cache_set(name: str, *, reason: str) -> None:
    key = str(name or "").strip()
    if not key:
        return
    ttl = _geocode_negative_cache_ttl()
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        _GEOCODE_NEGATIVE_CACHE[key] = {
            "reason": str(reason or "failed"),
            "updated_at": time.time(),
            "expires_at": time.time() + ttl,
        }
    _save_geocode_negative_cache(force=False)


def _geocode_negative_cache_clear(*names: str) -> None:
    keys = [str(name or "").strip() for name in names if str(name or "").strip()]
    if not keys:
        return
    changed = False
    with _GEOCODE_NEGATIVE_CACHE_LOCK:
        for key in keys:
            if _GEOCODE_NEGATIVE_CACHE.pop(key, None) is not None:
                changed = True
    if changed:
        _save_geocode_negative_cache(force=False)


def _load_geocode_cache() -> None:
    global _GEOCODE_CACHE_PATH
    _GEOCODE_CACHE_PATH = _resolve_geocode_cache_path()
    p = _GEOCODE_CACHE_PATH
    if not p or not os.path.exists(p):
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        with _GEOCODE_CACHE_LOCK:
            for k, v in data.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, list) and len(v) >= 2:
                    try:
                        lat = float(v[0])
                        lon = float(v[1])
                    except Exception:
                        continue
                    if _is_valid_coord(lat, lon):
                        _GEOCODE_CACHE[k] = (lat, lon)
                elif isinstance(v, dict) and "lat" in v and ("lon" in v or "lng" in v):
                    try:
                        lat = float(v.get("lat"))
                        lon = float(v.get("lon", v.get("lng")))
                    except Exception:
                        continue
                    if _is_valid_coord(lat, lon):
                        _GEOCODE_CACHE[k] = (lat, lon)
    except Exception:
        return


def _load_geocode_negative_cache() -> None:
    global _GEOCODE_NEGATIVE_CACHE_PATH
    _GEOCODE_NEGATIVE_CACHE_PATH = _resolve_geocode_negative_cache_path()
    p = _GEOCODE_NEGATIVE_CACHE_PATH
    if not p or not os.path.exists(p):
        return
    now = time.time()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        loaded: Dict[str, Dict[str, object]] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            expires_at = float(v.get("expires_at") or 0)
            if expires_at <= now:
                continue
            loaded[k] = {
                "reason": str(v.get("reason") or "failed"),
                "updated_at": float(v.get("updated_at") or now),
                "expires_at": expires_at,
            }
        with _GEOCODE_NEGATIVE_CACHE_LOCK:
            _GEOCODE_NEGATIVE_CACHE.clear()
            _GEOCODE_NEGATIVE_CACHE.update(loaded)
    except Exception:
        return


def _save_geocode_cache(force: bool = False) -> None:
    global _GEOCODE_CACHE_LAST_SAVE_TS
    p = _GEOCODE_CACHE_PATH or _resolve_geocode_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _GEOCODE_CACHE_LAST_SAVE_TS < 2.0):
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _GEOCODE_CACHE_LOCK:
            data = {k: [v[0], v[1]] for k, v in _GEOCODE_CACHE.items()}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _GEOCODE_CACHE_LAST_SAVE_TS = now
    except Exception:
        return


def _save_geocode_negative_cache(force: bool = False) -> None:
    global _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS
    p = _GEOCODE_NEGATIVE_CACHE_PATH or _resolve_geocode_negative_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS < 2.0):
        return
    _prune_geocode_negative_cache(now=now)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _GEOCODE_NEGATIVE_CACHE_LOCK:
            data = {
                k: {
                    "reason": str(v.get("reason") or "failed"),
                    "updated_at": float(v.get("updated_at") or now),
                    "expires_at": float(v.get("expires_at") or now),
                }
                for k, v in _GEOCODE_NEGATIVE_CACHE.items()
            }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS = now
    except Exception:
        return


def _geocode_cache_get(name: str) -> Optional[Tuple[float, float]]:
    if not name:
        return None
    with _GEOCODE_CACHE_LOCK:
        return _GEOCODE_CACHE.get(name)


def _geocode_cache_set(name: str, coord: Tuple[float, float]) -> None:
    if not name or not coord:
        return
    with _GEOCODE_CACHE_LOCK:
        _GEOCODE_CACHE[name] = coord
    _save_geocode_cache(force=False)

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


load_project_env(from_file=__file__, override=False)
_load_geocode_cache()
_load_geocode_negative_cache()


def _parse_latlon_pair(parts: Iterable[str]) -> Optional[Tuple[float, float]]:
    """
    将字符串列表解析为 (lat, lon)。
    - 如果出现纬度经度颠倒，则自动纠正。
    - 失败返回 None。
    """
    items = [p.strip() for p in parts if p.strip()]
    if len(items) != 2:
        return None
    try:
        a = float(items[0])
        b = float(items[1])
    except Exception:
        return None
    if abs(a) > 90 and abs(b) <= 90:
        # lon,lat → lat,lon
        return b, a
    if abs(b) > 90 and abs(a) <= 90:
        # lat,lon → lat,lon
        return a, b
    return a, b


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
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _looks_foreign_location(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    return any(m in value for m in _FOREIGN_LOCATION_MARKERS)


def _is_meaningful_place_candidate(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if value in _GEOCODE_REJECT_EXACT:
        return False
    return bool(re.search(r"[^\W_]", value, flags=re.UNICODE))


def _trim_geocode_candidate(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = _PAREN_CONTENT_RE.sub("", value)
    prev = None
    while value and value != prev:
        prev = value
        value = _GEOCODE_PREFIX_RE.sub("", value).strip()
    value = re.split(r"[\n\r]+", value, maxsplit=1)[0].strip()
    value = re.split(r"[，,。；;：:]", value, maxsplit=1)[0].strip()
    value = value.strip(" 、，,；;:：()（）[]【】<>《》\"'“”‘’")
    return value


def _reject_geocode_candidate_reason(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "empty"
    cleaned = _trim_geocode_candidate(raw)
    if not cleaned:
        return "empty_after_trim"
    if cleaned in _GEOCODE_REJECT_EXACT:
        return "generic_term"
    if any(pattern.search(raw) or pattern.search(cleaned) for pattern in _GEOCODE_REJECT_PATTERNS):
        return "non_place_phrase"
    if not _is_meaningful_place_candidate(cleaned):
        return "not_meaningful"
    return ""


def _log_rejected_geocode_candidate(original: str, reason: str, cleaned: str) -> None:
    _LOGGER.info(
        "geocode_candidate_rejected reason=%s original=%s candidate=%s",
        reason,
        str(original or "").strip(),
        str(cleaned or "").strip(),
    )


def _build_geocode_candidates(name: str) -> List[str]:
    base = str(name or "").strip()
    if not base:
        return []
    seen = set()
    items = [base]
    paren = re.findall(r"[（(]([^）)]+)[）)]", base)
    for p in paren:
        p = p.strip()
        if not p:
            continue
        if p.startswith("今") and len(p) > 1:
            items.append(p[1:].strip())
        items.append(p)
    split_markers = ["、", "，", ",", "；", ";", "和", "及", " / ", "/"]
    for m in split_markers:
        if m in base:
            left = base.split(m, 1)[0].strip()
            if left:
                items.append(left)
            break
    if _looks_foreign_location(base):
        for marker in sorted(_FOREIGN_LOCATION_MARKERS, key=len, reverse=True):
            if marker and base.startswith(marker):
                trimmed = base[len(marker):].strip(" ，,；;:/·•()（）")
                if trimmed:
                    items.append(trimmed)
    if (
        _looks_chinese(base)
        and "中国" not in base
        and "China" not in base
        and not _looks_foreign_location(base)
    ):
        items.append(f"中国{base}")
        items.append(f"{base} 中国")
    out = []
    for item in items:
        t = item.strip()
        cleaned = _trim_geocode_candidate(t)
        reason = _reject_geocode_candidate_reason(t)
        if reason:
            _log_rejected_geocode_candidate(t, reason, cleaned)
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _looks_like_place_description(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    markers = (
        "城市", "首都", "城镇", "聚居地", "行政区", "地区", "省", "州", "郡", "县", "村",
        "岛", "湖", "河", "山", "港", "共和国", "联邦", "王国", "capital", "city", "town",
        "village", "municipality", "county", "province", "region", "state", "country",
        "island", "lake", "river", "mountain", "settlement",
    )
    return any(marker in value for marker in markers)


def _looks_like_non_place_description(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    markers = (
        "人物", "作家", "诗人", "哲学家", "皇帝", "国王", "演员", "歌手", "导演", "政治家",
        "学者", "human", "person", "writer", "poet", "philosopher", "actor", "singer",
        "politician", "scientist",
    )
    return any(marker in value for marker in markers)


def _fetch_json(url: str, *, timeout: Optional[int] = None) -> Optional[object]:
    req = Request(url, headers={"User-Agent": _DEFAULT_USER_AGENT, "Accept": "application/json"})
    resolved_timeout = max(1, int(timeout or _fetch_timeout_seconds()))
    for attempt in range(3):
        try:
            with _GEOCODE_HTTP_SEM:
                _geocode_rate_limit()
                with urlopen(req, timeout=resolved_timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except HTTPError as exc:
            code = getattr(exc, "code", None)
            if code in {429, 503} and attempt < 2:
                time.sleep(0.8 * (attempt + 1))
                continue
            return None
        except (URLError, TimeoutError) as exc:
            message = str(exc or "").lower()
            if "timed out" in message or "timeout" in message:
                _record_geocode_metric("timeouts")
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None
        except Exception:
            return None
    return None


def _geocode_wikidata(name: str) -> Optional[Tuple[float, float]]:
    query = str(name or "").strip()
    if not _is_meaningful_place_candidate(query):
        return None
    _record_geocode_metric("wikidata_requests")
    for language in ("zh", "en"):
        search_url = _WIKIDATA_SEARCH_ENDPOINT.format(language=quote(language), query=quote(query))
        payload = _fetch_json(search_url)
        if not isinstance(payload, dict):
            continue
        items = payload.get("search") or []
        if not isinstance(items, list):
            continue
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("id") or "").strip()
            if not entity_id:
                continue
            description = str(item.get("description") or "").strip()
            if _looks_like_non_place_description(description):
                continue
            if description and not _looks_like_place_description(description):
                continue
            entity_url = _WIKIDATA_ENTITY_ENDPOINT.format(entity_id=quote(entity_id))
            entity_payload = _fetch_json(entity_url)
            if not isinstance(entity_payload, dict):
                continue
            entity = ((entity_payload.get("entities") or {}) if isinstance(entity_payload.get("entities"), dict) else {}).get(entity_id)
            claims = (entity or {}).get("claims") if isinstance(entity, dict) else None
            coord_claims = claims.get("P625") if isinstance(claims, dict) else None
            if not isinstance(coord_claims, list) or not coord_claims:
                continue
            for claim in coord_claims:
                mainsnak = claim.get("mainsnak") if isinstance(claim, dict) else None
                datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None
                value = datavalue.get("value") if isinstance(datavalue, dict) else None
                if not isinstance(value, dict):
                    continue
                lat = value.get("latitude")
                lon = value.get("longitude")
                if _is_valid_coord(lat, lon):
                    _record_geocode_metric("wikidata_successes")
                    return float(lat), float(lon)
    _record_geocode_metric("wikidata_failures")
    return None


def _geocode_nominatim(name: str, force_cn: bool = False) -> Optional[Tuple[float, float]]:
    """
    公共地理编码回退链路：
    - nominatim.openstreetmap.org
    - geocode.maps.co
    - photon.komoot.io
    """
    if not name:
        return None
    _record_geocode_metric("nominatim_requests")
    country_param = "&countrycodes=cn" if force_cn else ""
    mapsco_key = (os.getenv("MAPSCO_API_KEY") or "").strip()
    for url_tpl, kind in _GEOCODE_ENDPOINTS:
        if "geocode.maps.co" in url_tpl and not mapsco_key:
            continue
        url = ""
        if "geocode.maps.co" in url_tpl:
            url = f"{url_tpl.format(quote(name))}&api_key={quote(mapsco_key)}"
        else:
            url = url_tpl.format(quote(name))
        if kind == "list" and country_param:
            url = f"{url}{country_param}"
        req = Request(url, headers={"User-Agent": _DEFAULT_USER_AGENT})
        for attempt in range(3):
            try:
                with _GEOCODE_HTTP_SEM:
                    _geocode_rate_limit()
                    with urlopen(req, timeout=_nominatim_timeout_seconds()) as resp:
                        data = resp.read()
                payload = json.loads(data.decode("utf-8", errors="ignore"))
                if kind == "list" and isinstance(payload, list) and payload:
                    lat = float(payload[0].get("lat"))
                    lon = float(payload[0].get("lon"))
                    if not force_cn or _is_inside_china(lat, lon):
                        _record_geocode_metric("nominatim_successes")
                        return lat, lon
                if kind == "photon" and isinstance(payload, dict):
                    features = payload.get("features") or []
                    if features:
                        coords = features[0].get("geometry", {}).get("coordinates") or []
                        if len(coords) >= 2:
                            lon = float(coords[0])
                            lat = float(coords[1])
                            if not force_cn or _is_inside_china(lat, lon):
                                _record_geocode_metric("nominatim_successes")
                                return lat, lon
                break
            except HTTPError as exc:
                code = getattr(exc, "code", None)
                if code in {429, 503} and attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                _LOGGER.warning("geocode_failed name=%s error=%s", name, exc)
                break
            except (URLError, TimeoutError) as exc:
                message = str(exc or "").lower()
                if "timed out" in message or "timeout" in message:
                    _record_geocode_metric("timeouts")
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                _LOGGER.warning("geocode_failed name=%s error=%s", name, exc)
                break
            except Exception as exc:
                _LOGGER.warning("geocode_failed name=%s error=%s", name, exc)
                break
    _record_geocode_metric("nominatim_failures")
    return None


def _amap_rate_limit() -> None:
    min_interval = float(os.getenv("MAP_STORY_AMAP_MIN_INTERVAL", "0.12"))
    if min_interval <= 0:
        return
    global _AMAP_LAST_REQ_TS
    with _AMAP_RL_LOCK:
        now = time.monotonic()
        wait = (_AMAP_LAST_REQ_TS + min_interval) - now
        if wait > 0:
            time.sleep(wait)
        _AMAP_LAST_REQ_TS = time.monotonic()


def _amap_webservice_geocode(address: str) -> Optional[Tuple[float, float]]:
    key = (
        (os.getenv("locaion_api") or "").strip()
        or (os.getenv("location_api") or "").strip()
        or (os.getenv("LOCATION_API") or "").strip()
        or (os.getenv("AMAP_WEBSERVICE_KEY") or "").strip()
        or (os.getenv("AMAP_WEB_SERVICE_KEY") or "").strip()
        or (os.getenv("AMAP_REST_KEY") or "").strip()
    )
    addr = str(address or "").strip()
    if not key or not addr:
        return None
    _record_geocode_metric("amap_requests")
    url = f"https://restapi.amap.com/v3/geocode/geo?address={quote(addr)}&key={quote(key)}"
    req = Request(url, headers={"User-Agent": _DEFAULT_USER_AGENT})
    for attempt in range(3):
        try:
            with _GEOCODE_HTTP_SEM:
                _amap_rate_limit()
                with urlopen(req, timeout=_amap_timeout_seconds()) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if not isinstance(payload, dict) or str(payload.get("status")) != "1":
                return None
            geocodes = payload.get("geocodes")
            if not isinstance(geocodes, list) or not geocodes:
                return None
            g0 = geocodes[0] if isinstance(geocodes[0], dict) else None
            if not isinstance(g0, dict):
                return None
            loc = str(g0.get("location") or "").strip()
            if not loc or "," not in loc:
                return None
            a, b = loc.split(",", 1)
            lon = float(a.strip())
            lat = float(b.strip())
            if not _is_valid_coord(lat, lon):
                return None
            _record_geocode_metric("amap_successes")
            return _gcj02_to_wgs84(lat, lon)
        except HTTPError as exc:
            code = getattr(exc, "code", None)
            if code in {429, 503} and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            _LOGGER.warning("amap_geocode_failed name=%s error=%s", addr, exc)
            return None
        except (URLError, TimeoutError) as exc:
            message = str(exc or "").lower()
            if "timed out" in message or "timeout" in message:
                _record_geocode_metric("timeouts")
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            _LOGGER.warning("amap_geocode_failed name=%s error=%s", addr, exc)
            return None
        except Exception as exc:
            _LOGGER.warning("amap_geocode_failed name=%s error=%s", addr, exc)
            return None
    _record_geocode_metric("amap_failures")
    return None


def geocode_city(name: str) -> Optional[Tuple[float, float]]:
    """城市/地址字符串 → WGS84 经纬度。

    - 若命中高德 WebService 地理编码（通常为 GCJ-02），则在落库/渲染前统一转换为 WGS84。
    - 若回退公共地理编码（OSM 系），则其结果本身即为 WGS84。
    """
    name = str(name or "").strip()
    if not name:
        return None
    _record_geocode_metric("lookups")
    candidates = _build_geocode_candidates(name)
    looks_cn = _looks_chinese(name)
    looks_foreign = _looks_foreign_location(name)
    # 优先使用命中缓存，减少外部地理编码调用
    cached = _geocode_cache_get(name)
    if cached:
        _record_geocode_metric("cache_hits")
        return cached
    negative_cached = _geocode_negative_cache_get(name)
    if negative_cached:
        _record_geocode_metric("negative_cache_hits")
        return None
    _record_geocode_metric("misses")
    if looks_cn and not looks_foreign:
        for cand in candidates:
            res = _amap_webservice_geocode(cand)
            if res:
                _geocode_cache_set(name, res)
                _geocode_cache_set(cand, res)
                _geocode_negative_cache_clear(name, cand)
                _record_geocode_metric("successes")
                return res
    if looks_foreign or not looks_cn:
        for cand in candidates:
            res = _geocode_wikidata(cand)
            if res:
                _geocode_cache_set(name, res)
                _geocode_cache_set(cand, res)
                _geocode_negative_cache_clear(name, cand)
                _record_geocode_metric("successes")
                return res
    for cand in candidates:
        res = _geocode_nominatim(cand, force_cn=looks_cn and not looks_foreign)
        if res:
            _geocode_cache_set(name, res)
            _geocode_cache_set(cand, res)
            _geocode_negative_cache_clear(name, cand)
            _record_geocode_metric("successes")
            return res
    # 有些国外城市会以纯中文形式出现，例如“都柏林”。这会让首轮查询看起来像
    # 国内地点；如果带中国偏置的检索失败，需要再走一轮更适合国外地点的兜底。
    if looks_cn and not looks_foreign:
        for cand in candidates:
            res = _geocode_wikidata(cand)
            if res:
                _geocode_cache_set(name, res)
                _geocode_cache_set(cand, res)
                _geocode_negative_cache_clear(name, cand)
                _record_geocode_metric("successes")
                return res
        for cand in candidates:
            res = _geocode_nominatim(cand, force_cn=False)
            if res:
                _geocode_cache_set(name, res)
                _geocode_cache_set(cand, res)
                _geocode_negative_cache_clear(name, cand)
                _record_geocode_metric("successes")
                return res
    _geocode_negative_cache_set(name, reason="no_result")
    _record_geocode_metric("failures")
    return None


def _clean_place_name(text: str) -> str:
    """
    去除地名中的括注内容，保留核心名称，提升地理编码命中率。
    """
    if not isinstance(text, str):
        return ""
    text = _PAREN_CONTENT_RE.sub("", text)
    return text.strip()


def extract_places_in_order(md: str) -> List[str]:
    """
    从“年份/生平时间线”表解析地点，优先使用“现代搜索地名”列，按出现顺序返回地点列表（去重保序）。
    """
    if not isinstance(md, str):
        return []
    lines = md.splitlines()
    in_loc = False
    table_started = False
    display_idx = None
    search_idx = None
    places: List[str] = []
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            if title.startswith("年份") or "生平时间线" in title:
                in_loc = True
                table_started = False
                display_idx = None
                search_idx = None
                continue
            else:
                in_loc = False
        if not in_loc:
            continue
        if line.strip().startswith("|") and not table_started:
            table_started = True
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            for j, c in enumerate(header_cells):
                if search_idx is None and "现代搜索地名" in c:
                    search_idx = j
                if display_idx is None and ("现称" in c or "地点" in c):
                    display_idx = j
            continue
        if table_started:
            stripped = line.strip()
            if _TABLE_SEPARATOR_RE.match(stripped):
                continue
            if stripped.startswith("|"):
                if search_idx is None and display_idx is None:
                    continue
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                cell = ""
                if search_idx is not None and search_idx < len(cells):
                    cell = cells[search_idx]
                if not cell and display_idx is not None and display_idx < len(cells):
                    cell = cells[display_idx]
                if cell:
                    if "：" in cell:
                        cell = cell.split("：", 1)[-1].strip()
                    clean = _clean_place_name(cell)
                    if clean and clean != "—":
                        places.append(clean)
            else:
                break
    if not places:
        return []
    return list(dict.fromkeys(places))


def _strip_auto_coords_section(md: str) -> str:
    if not isinstance(md, str):
        return ""
    if "地点坐标（自动地理编码）" not in md:
        return md
    lines = md.splitlines()
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            if "地点坐标（自动地理编码）" in title:
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            out.append(line)
    while len(out) >= 2 and (not out[-1].strip()) and (not out[-2].strip()):
        out.pop()
    return "\n".join(out)


def append_coords_section(md: str) -> str:
    """
    依据“年份”表逐个地理编码，并在文末追加“地点坐标（自动地理编码）”表。
    如果没有识别出地点或均编码失败，则不做改动直接返回原文。
    """
    if not isinstance(md, str):
        return ""
    base_md = _strip_auto_coords_section(md)
    changed = base_md != md
    lines = base_md.splitlines()
    coords: Dict[str, Tuple[float, float]] = {}
    places = extract_places_in_order(base_md)
    if not places:
        return base_md if changed else md
    max_workers = min(8, max(1, len(places)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(geocode_city, p): p for p in places}
        for future in as_completed(future_map):
            place = future_map[future]
            try:
                coord = future.result()
            except Exception:
                coord = None
            if coord:
                coords[place] = coord
    if not coords:
        return base_md if changed else md
    section = []
    section.append("")
    section.append("## 地点坐标（自动地理编码）")
    section.append("| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |")
    section.append("| --- | --- | --- | --- | --- |")
    for p in places:
        if p in coords:
            lat, lon = coords[p]
            section.append(f"| {p} | {p} | {lat:.6f} | {lon:.6f} | WGS84 |")
    return "\n".join(lines + section)


def compute_total_distance_km(md: str) -> Optional[float]:
    """
    从“地点坐标（自动地理编码）”表获取经纬度，计算总直线距离（公里）。
    使用 Haversine 公式计算。
    """
    if not isinstance(md, str):
        return None
    coords: List[Tuple[float, float]] = []
    lines = md.splitlines()
    in_section = False
    header_seen = False
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_section = "地点坐标" in title
            header_seen = False
            continue
        if not in_section:
            continue
        if line.strip().startswith("|") and not header_seen:
            header_seen = True
            continue
        if header_seen:
            if not line.strip().startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                lat_idx, lon_idx = 2, 3
            elif len(cells) >= 3:
                lat_idx, lon_idx = 1, 2
            else:
                continue
            try:
                lat = float(cells[lat_idx])
                lon = float(cells[lon_idx])
                coords.append((lat, lon))
            except Exception:
                continue
    if len(coords) < 2:
        return None
    total = 0.0
    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]
        total += _haversine(lat1, lon1, lat2, lon2)
    return total


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dLon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def insert_distance_intro(md: str, distance_km: float) -> str:
    """
    在“人生足迹地图说明”中插入总行程描述。
    """
    if not isinstance(md, str):
        return ""
    lines = md.splitlines()
    out: List[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.strip().startswith("## 二、人生足迹地图说明"):
            continue
        if not inserted and line.strip().startswith("- 🌟 **重要节点数量**"):
            out.append(f"- 🚶 **总行程估算**：约 {distance_km:.0f} 公里")
            inserted = True
    return "\n".join(out)
