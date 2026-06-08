from __future__ import annotations

import atexit
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from .artifacts import _project_root
    from .env_utils import apply_story_map_env_aliases, load_project_env
    from .map_client import geocode_city
    from .story_agents import StoryAgentLLM
except ImportError:
    from artifacts import _project_root
    from env_utils import apply_story_map_env_aliases, load_project_env
    from map_client import geocode_city
    from story_agents import StoryAgentLLM


load_project_env(from_file=__file__, override=True)
apply_story_map_env_aliases()

_LOGGER = logging.getLogger("story_map.geocode")
_BANNED_PLACE_KEYS = {"中国", "全国", "世界", "海外", "国内", "各地"}

_HISTORICAL_INDEX: Optional[Dict[str, Tuple[float, float]]] = None
_HISTORICAL_INDEX_LOCK = threading.Lock()
_PLACE_ALIASES: Optional[Dict[str, Dict[str, object]]] = None
_PLACE_ALIASES_LOCK = threading.Lock()
_TGAZ_CACHE: Dict[str, Optional[Tuple[float, float]]] = {}
_TGAZ_CACHE_LOCK = threading.Lock()
_TGAZ_CACHE_PATH: Optional[str] = None
_TGAZ_CACHE_LAST_SAVE_TS = 0.0
_TGAZ_RL_LOCK = threading.Lock()
_TGAZ_LAST_REQ_TS = 0.0
_LLM_CLIENT: Optional[StoryAgentLLM] = None
_LLM_LOCK = threading.Lock()
_SPLIT_CACHE: Dict[str, Tuple[str, str]] = {}
_CACHE_LOCK = threading.Lock()


def _get_llm_client(event_callback: Optional[callable] = None) -> StoryAgentLLM:
    global _LLM_CLIENT
    if event_callback:
        return StoryAgentLLM(event_callback=event_callback)
    if _LLM_CLIENT is None:
        with _LLM_LOCK:
            if _LLM_CLIENT is None:
                _LLM_CLIENT = StoryAgentLLM()
    return _LLM_CLIENT


def normalize_place_key(text: str) -> str:
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[\s\t\r\n]+", "", s)
    s = re.sub(r"[（(].*?[）)]", "", s)
    s = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", s)
    s = re.sub(r"(一带|附近|周边|地区|境内|境外|等地|之地|左右|一线)$", "", s)
    return s.strip()


def _resolve_tgaz_cache_path() -> str:
    p = (os.getenv("MAP_STORY_TGAZ_CACHE") or "").strip()
    if p:
        return os.path.abspath(os.path.expanduser(p))
    return os.path.join(_project_root(), ".cache", "story_map_tgaz_cache.json")


def _place_alias_candidates() -> List[str]:
    env_path = os.getenv("MAP_STORY_PLACE_ALIASES", "").strip()
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    repo_root = _project_root()
    candidates.extend(
        [
            os.path.join(repo_root, "data", "place_aliases.json"),
            os.path.join(repo_root, "storymap", "data", "place_aliases.json"),
        ]
    )
    seen = set()
    out: List[str] = []
    for path in candidates:
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path in seen:
            continue
        seen.add(abs_path)
        out.append(abs_path)
    return out


def _load_place_aliases() -> Dict[str, Dict[str, object]]:
    alias_path = ""
    for candidate in _place_alias_candidates():
        if os.path.exists(candidate) and os.path.isfile(candidate):
            alias_path = candidate
            break
    if not alias_path:
        return {}
    try:
        raw = json.loads(Path(alias_path).read_text(encoding="utf-8"))
    except Exception as exc:
        _LOGGER.warning("加载地名别名表失败: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}

    alias_map: Dict[str, Dict[str, object]] = {}
    for alias, value in raw.items():
        norm_alias = normalize_place_key(alias)
        if not norm_alias:
            continue
        entry: Dict[str, object] = {"names": []}
        if isinstance(value, str):
            entry["names"] = [value]
        elif isinstance(value, list):
            if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                entry["coords"] = (float(value[0]), float(value[1]))
            else:
                entry["names"] = [str(item).strip() for item in value if str(item or "").strip()]
        elif isinstance(value, dict):
            names_raw = value.get("names") or []
            if isinstance(names_raw, str):
                entry["names"] = [names_raw.strip()] if names_raw.strip() else []
            elif isinstance(names_raw, list):
                entry["names"] = [str(item).strip() for item in names_raw if str(item or "").strip()]
            coords_raw = value.get("coords")
            if (
                isinstance(coords_raw, list)
                and len(coords_raw) >= 2
                and all(isinstance(item, (int, float)) for item in coords_raw[:2])
            ):
                entry["coords"] = (float(coords_raw[0]), float(coords_raw[1]))
        if not entry.get("names") and not entry.get("coords"):
            continue
        alias_map[norm_alias] = entry
    return alias_map


def _expand_place_candidates(*names: str) -> Tuple[List[str], Optional[Tuple[float, float]]]:
    global _PLACE_ALIASES
    with _PLACE_ALIASES_LOCK:
        if _PLACE_ALIASES is None:
            _PLACE_ALIASES = _load_place_aliases()
        alias_map = _PLACE_ALIASES or {}

    expanded: List[str] = []
    seen_norm = set()
    queue: List[str] = [str(name).strip() for name in names if str(name or "").strip()]
    direct_coord: Optional[Tuple[float, float]] = None

    while queue:
        current = queue.pop(0)
        norm = normalize_place_key(current)
        if not norm or norm in seen_norm:
            continue
        seen_norm.add(norm)
        expanded.append(current)
        entry = alias_map.get(norm) or {}
        coords = entry.get("coords")
        if direct_coord is None and isinstance(coords, tuple) and len(coords) >= 2:
            direct_coord = (float(coords[0]), float(coords[1]))
        for alias_name in entry.get("names") or []:
            alias_text = str(alias_name or "").strip()
            alias_norm = normalize_place_key(alias_text)
            if alias_text and alias_norm and alias_norm not in seen_norm:
                queue.append(alias_text)
    return expanded, direct_coord


def _load_tgaz_cache() -> None:
    global _TGAZ_CACHE_PATH
    _TGAZ_CACHE_PATH = _resolve_tgaz_cache_path()
    p = _TGAZ_CACHE_PATH
    if not p or not os.path.exists(p):
        return
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    with _TGAZ_CACHE_LOCK:
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            if value is None:
                _TGAZ_CACHE[key] = None
                continue
            if isinstance(value, list) and len(value) >= 2:
                try:
                    lat = float(value[0])
                    lon = float(value[1])
                except Exception:
                    continue
                _TGAZ_CACHE[key] = (lat, lon)


def _save_tgaz_cache(force: bool = False) -> None:
    global _TGAZ_CACHE_LAST_SAVE_TS
    p = _TGAZ_CACHE_PATH or _resolve_tgaz_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _TGAZ_CACHE_LAST_SAVE_TS < 2.0):
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _TGAZ_CACHE_LOCK:
            data = {k: (None if v is None else [float(v[0]), float(v[1])]) for k, v in _TGAZ_CACHE.items()}
        Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _TGAZ_CACHE_LAST_SAVE_TS = now
    except Exception:
        return


def _tgaz_rate_limit() -> None:
    min_interval = float(os.getenv("MAP_STORY_TGAZ_MIN_INTERVAL", "1.1"))
    if min_interval <= 0:
        return
    global _TGAZ_LAST_REQ_TS
    with _TGAZ_RL_LOCK:
        now = time.monotonic()
        wait = (_TGAZ_LAST_REQ_TS + min_interval) - now
        if wait > 0:
            time.sleep(wait)
        _TGAZ_LAST_REQ_TS = time.monotonic()


def _historical_index_candidates() -> List[str]:
    env_path = os.getenv("HISTORICAL_PLACES_INDEX", "").strip()
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = _project_root()
    candidates.extend(
        [
            os.path.join(here, "historical_places_index.jsonl"),
            os.path.join(here, "..", "historical_places_index.jsonl"),
            os.path.join(here, "..", "..", "historical_places_index.jsonl"),
            os.path.join(repo_root, "historical_places_index.jsonl"),
            os.path.join(repo_root, "data", "historical_places_index.jsonl"),
            os.path.join(os.getcwd(), "historical_places_index.jsonl"),
        ]
    )
    abs_candidates: List[str] = []
    seen = set()
    for path in candidates:
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path in seen:
            continue
        seen.add(abs_path)
        abs_candidates.append(abs_path)
    return abs_candidates


def _load_historical_places_index() -> Dict[str, Tuple[float, float]]:
    mapping: Dict[str, Tuple[float, float]] = {}
    index_path = ""
    for candidate in _historical_index_candidates():
        if os.path.exists(candidate) and os.path.isfile(candidate):
            index_path = candidate
            break
    if not index_path:
        return mapping
    try:
        with open(index_path, "r", encoding="utf-8") as f:
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
                try:
                    lat_f = float(obj.get("lat"))
                    lon_f = float(obj.get("lon"))
                except Exception:
                    continue
                for key in [ancient, modern]:
                    norm = normalize_place_key(key)
                    if norm and norm not in mapping:
                        mapping[norm] = (lat_f, lon_f)
    except Exception as exc:
        _LOGGER.warning("加载古地名索引库失败: %s", exc)
        return {}
    return mapping


def lookup_coords_from_historical_index(*names: str) -> Optional[Tuple[float, float]]:
    expanded_names, direct_coord = _expand_place_candidates(*names)
    if direct_coord:
        return direct_coord
    global _HISTORICAL_INDEX
    with _HISTORICAL_INDEX_LOCK:
        if _HISTORICAL_INDEX is None:
            _HISTORICAL_INDEX = _load_historical_places_index()
        mapping = _HISTORICAL_INDEX or {}
    for name in expanded_names:
        norm = normalize_place_key(name)
        if not norm:
            continue
        coord = mapping.get(norm)
        if coord:
            return coord
    return None


def _tgaz_query(name: str, year: Optional[int]) -> Optional[Tuple[float, float]]:
    n = str(name or "").strip()
    if not n:
        return None
    yr = None
    if isinstance(year, int) and -222 <= year <= 1911:
        yr = year
    cache_key = f"{n}|{yr if yr is not None else ''}"
    with _TGAZ_CACHE_LOCK:
        if cache_key in _TGAZ_CACHE:
            return _TGAZ_CACHE[cache_key]
    base = "https://chgis.hudci.org/tgaz/placename"
    url = f"{base}?fmt=json&n={quote(n, safe='')}"
    if yr is not None:
        url += f"&yr={yr}"
    try:
        _tgaz_rate_limit()
        req = Request(url, headers={"User-Agent": "StoryMap/1.0"})
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        with _TGAZ_CACHE_LOCK:
            _TGAZ_CACHE[cache_key] = None
        _save_tgaz_cache(force=False)
        return None
    items = data.get("placenames") if isinstance(data, dict) else None
    if not isinstance(items, list):
        with _TGAZ_CACHE_LOCK:
            _TGAZ_CACHE[cache_key] = None
        _save_tgaz_cache(force=False)
        return None

    def parse_xy(value: str) -> Optional[Tuple[float, float]]:
        try:
            parts = [p.strip() for p in str(value).split(",")]
            if len(parts) != 2:
                return None
            x = float(parts[0])
            y = float(parts[1])
            if abs(x) < 1e-6 and abs(y) < 1e-6:
                return None
            return (y, x)
        except Exception:
            return None

    best = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("object type") or "").upper() != "POINT":
            continue
        xy = parse_xy(item.get("xy coordinates") or "")
        if not xy:
            continue
        best = xy
        break
    if best is None:
        for item in items:
            if not isinstance(item, dict):
                continue
            xy = parse_xy(item.get("xy coordinates") or "")
            if not xy:
                continue
            best = xy
            break
    with _TGAZ_CACHE_LOCK:
        _TGAZ_CACHE[cache_key] = best
    _save_tgaz_cache(force=False)
    return best


def resolve_place_coord(place: str, year: Optional[int] = None, *aliases: str) -> Optional[Tuple[float, float]]:
    candidates = [place] + [alias for alias in aliases if alias]
    expanded_names, direct_coord = _expand_place_candidates(*candidates)
    if direct_coord:
        return direct_coord
    coord = lookup_coords_from_historical_index(*expanded_names)
    if coord:
        return coord
    for cand in expanded_names:
        coord = _tgaz_query(cand, year)
        if coord:
            return coord
    for cand in expanded_names:
        try:
            return geocode_city(cand)
        except Exception:
            continue
    return None


def _parse_split_json(raw: str) -> Tuple[str, str]:
    try:
        data = json.loads(raw.strip())
        if isinstance(data, dict):
            ancient = str(data.get("ancient", "")).strip()
            modern = str(data.get("modern", "")).strip()
            return ancient, modern
    except Exception as exc:
        _LOGGER.warning("解析地名拆解 JSON 失败: %s (Raw: %s)", exc, raw[:100])
    return "", ""


def _extract_json_block(raw: str) -> str:
    text = raw.strip()
    for start, end in [("[", "]"), ("{", "}")]:
        idx = text.find(start)
        if idx == -1:
            continue
        tail = text[idx:]
        end_idx = tail.rfind(end)
        if end_idx != -1:
            return tail[: end_idx + 1]
    return text


def _parse_split_batch(raw: str, expected: List[str]) -> Dict[str, Tuple[str, str]]:
    block = _extract_json_block(raw)
    try:
        data = json.loads(block)
    except Exception:
        return {}
    mapping: Dict[str, Tuple[str, str]] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text = item.get("text") or item.get("loc") or item.get("name") or item.get("source") or ""
                if not text and len(expected) == 1:
                    text = expected[0]
                text = str(text).strip()
                ancient = str(item.get("ancient", "")).strip()
                modern = str(item.get("modern", "")).strip()
                if text:
                    mapping[text] = (ancient, modern)
            elif isinstance(item, list) and len(item) >= 3:
                text = str(item[0]).strip()
                ancient = str(item[1]).strip()
                modern = str(item[2]).strip()
                if text:
                    mapping[text] = (ancient, modern)
        return mapping
    if isinstance(data, dict):
        for key, value in data.items():
            text = str(key).strip()
            if not text:
                continue
            ancient = ""
            modern = ""
            if isinstance(value, dict):
                ancient = str(value.get("ancient", "")).strip()
                modern = str(value.get("modern", "")).strip()
            elif isinstance(value, list):
                if len(value) > 0:
                    ancient = str(value[0]).strip()
                if len(value) > 1:
                    modern = str(value[1]).strip()
            else:
                modern = str(value).strip()
            mapping[text] = (ancient, modern)
    return mapping


def split_ancient_modern_heuristic(loc_text: str) -> Tuple[str, str]:
    text = str(loc_text or "").strip()
    if not text:
        return "", ""
    modern = ""
    ancient = ""
    m = re.search(r"[（(]\s*今(?:称)?\s*([^）)]+)\s*[）)]", text)
    if m:
        modern = m.group(1).strip()
        ancient = re.sub(r"[（(].*?[）)]", "", text).strip()
        ancient = re.sub(r"^(古称|又称|旧称)[:：]?\s*", "", ancient).strip()
        return ancient, modern
    m = re.search(r"\b今(?:称)?\s*([^\s，。；;、/]+)", text)
    if m:
        modern = m.group(1).strip()
        rest = text[: m.start()].strip()
        rest = re.sub(r"[（(].*?[）)]", "", rest).strip()
        rest = re.sub(r"^(古称|又称|旧称)[:：]?\s*", "", rest).strip()
        ancient = rest
        return ancient, modern
    return "", ""


def batch_split_ancient_modern(
    loc_texts: List[str],
    event_callback: Optional[callable] = None,
) -> Dict[str, Tuple[str, str]]:
    texts = [t.strip() for t in loc_texts if t and t.strip()]
    if not texts:
        return {}
    seen = set()
    ordered: List[str] = []
    for text in texts:
        if text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    with _CACHE_LOCK:
        pending = [text for text in ordered if text not in _SPLIT_CACHE]
    if not pending:
        with _CACHE_LOCK:
            return {text: _SPLIT_CACHE[text] for text in ordered if text in _SPLIT_CACHE}
    use_llm = str(os.getenv("STORY_MAP_ENABLE_LLM_SPLIT", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
    if not use_llm:
        with _CACHE_LOCK:
            for text in pending:
                if text in _SPLIT_CACHE:
                    continue
                _SPLIT_CACHE[text] = split_ancient_modern_heuristic(text)
            return {text: _SPLIT_CACHE.get(text, ("", "")) for text in ordered}
    try:
        client = _get_llm_client(event_callback=event_callback)
    except Exception as exc:
        _LOGGER.warning("LLM 客户端初始化失败，回退至启发式拆解逻辑: %s", exc)
        with _CACHE_LOCK:
            for text in pending:
                if text in _SPLIT_CACHE:
                    continue
                _SPLIT_CACHE[text] = split_ancient_modern_heuristic(text)
            return {text: _SPLIT_CACHE.get(text, ("", "")) for text in ordered}
    sys_prompt = (
        "你是地名拆解助手。请按输入顺序输出严格 JSON 数组，"
        "元素格式为 {\"text\":\"\",\"ancient\":\"\",\"modern\":\"\"}。"
        "无法判断时 ancient/modern 置空。不要输出多余文本。"
    )
    for i in range(0, len(pending), 20):
        chunk = pending[i : i + 20]
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"地名列表：{json.dumps(chunk, ensure_ascii=False)}"},
        ]
        raw = client.think(messages, temperature=0)
        mapping = _parse_split_batch(raw or "", chunk)
        with _CACHE_LOCK:
            for text in chunk:
                if text in _SPLIT_CACHE:
                    continue
                _SPLIT_CACHE[text] = mapping.get(text) or ("", "")
    with _CACHE_LOCK:
        return {text: _SPLIT_CACHE.get(text, ("", "")) for text in ordered}


def split_ancient_modern(
    loc_text: str,
    event_callback: Optional[callable] = None,
) -> Tuple[str, str]:
    if not loc_text:
        return "", ""
    with _CACHE_LOCK:
        cached = _SPLIT_CACHE.get(loc_text)
    if cached:
        return cached
    use_llm = str(os.getenv("STORY_MAP_ENABLE_LLM_SPLIT", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
    if not use_llm:
        result = split_ancient_modern_heuristic(loc_text)
        with _CACHE_LOCK:
            _SPLIT_CACHE[loc_text] = result
        return result
    try:
        client = _get_llm_client(event_callback=event_callback)
    except Exception as exc:
        _LOGGER.warning("LLM 客户端初始化失败，回退至启发式拆解逻辑: %s", exc)
        result = split_ancient_modern_heuristic(loc_text)
        with _CACHE_LOCK:
            _SPLIT_CACHE[loc_text] = result
        return result
    prompts = [
        "你是地名拆解助手。仅返回严格 JSON：{\"ancient\":\"\",\"modern\":\"\"}。不要输出多余文本。无法判断时输出空字符串。",
        "请只输出 JSON 对象，不要任何解释：{\"ancient\":\"古称或历史地名\",\"modern\":\"现代地名\"}。如果无法判断，两个值都输出空字符串。",
    ]
    ancient = ""
    modern = ""
    for sys_prompt in prompts:
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"地名文本：{loc_text}"},
        ]
        raw = client.think(messages, temperature=0)
        if not raw:
            continue
        ancient_text, modern_text = _parse_split_json(raw)
        if ancient_text or modern_text:
            ancient, modern = ancient_text, modern_text
            break
    result = (ancient, modern)
    with _CACHE_LOCK:
        _SPLIT_CACHE[loc_text] = result
    return result


def fuzzy_coord_lookup(
    coords_cache: Dict[str, Tuple[float, float]],
    candidates: List[str],
) -> Optional[Tuple[float, float]]:
    if not coords_cache:
        return None
    raw_candidates = [str(candidate or "").strip() for candidate in candidates if str(candidate or "").strip()]
    for candidate in raw_candidates:
        if candidate in coords_cache:
            return coords_cache.get(candidate)
    candidate_norms = [(normalize_place_key(candidate), candidate) for candidate in raw_candidates]
    candidate_norms = [(norm, raw) for norm, raw in candidate_norms if norm]
    if not candidate_norms:
        return None
    scored: List[Tuple[int, str]] = []
    for key in coords_cache.keys():
        raw_key = str(key or "").strip()
        if not raw_key:
            continue
        norm_key = normalize_place_key(raw_key)
        if not norm_key or norm_key in _BANNED_PLACE_KEYS or len(norm_key) < 2:
            continue
        for candidate_norm, _ in candidate_norms:
            if norm_key and candidate_norm and (norm_key in candidate_norm or candidate_norm in norm_key):
                scored.append((len(norm_key), raw_key))
                break
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return coords_cache.get(scored[0][1])


_load_tgaz_cache()
atexit.register(_save_tgaz_cache, True)

_normalize_place_key = normalize_place_key
_lookup_coords_from_historical_index = lookup_coords_from_historical_index
_resolve_place_coord = resolve_place_coord
_split_ancient_modern_heuristic = split_ancient_modern_heuristic
_split_ancient_modern = split_ancient_modern
_batch_split_ancient_modern = batch_split_ancient_modern
_fuzzy_coord_lookup = fuzzy_coord_lookup
