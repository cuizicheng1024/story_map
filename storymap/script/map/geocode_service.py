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

from ..agent.registry import StoryAgentLLM
from ..core.parsers import BANNED_PLACE_KEYS
from ..core.project_paths import project_root_path
from ..core.env_utils import apply_story_map_env_aliases, load_project_env
from .map_client import _is_inside_china, _is_inside_china_mainland, _looks_chinese, geocode_city, _looks_foreign_location

load_project_env(from_file=__file__, override=False)
apply_story_map_env_aliases()

_LOGGER = logging.getLogger("story_map.geocode")
_PLACE_REJECT_PATTERNS = (
    re.compile(r"(?:待考|不详|未知|存疑|说法不一|一说|另说|传说|推测|可能|未详|无确切|史载不详)"),
    re.compile(r"(?:具体|确切).{0,8}(?:位置|地点|地名)"),
    re.compile(r"(?:位置|地点|地名).{0,8}(?:不详|待考|存疑|未知|不明)"),
    re.compile(r"(?:出生|去世|逝世|卒|死亡)(?:地|于)?$"),
)
_PLACE_REJECT_EXACT = {
    "",
    "不详",
    "未知",
    "地点",
    "位置",
    "地名",
    "某地",
    "当地",
    "此地",
    "这里",
    "那里",
    "出生",
    "去世",
    "出生地",
    "去世地",
    "逝世",
    "死亡",
    "中国去世",
    "中国出生",
}


class _GeocodeState:
    """单例：封装地理编码服务的所有模块级全局状态与缓存。"""

    def __init__(self) -> None:
        self.historical_index: Optional[Dict[str, Tuple[float, float]]] = None
        self.historical_index_lock = threading.Lock()
        self.place_aliases: Optional[Dict[str, List[Dict[str, object]]]] = None
        self.place_aliases_lock = threading.Lock()
        self.place_name_index: Optional[Dict[str, List[str]]] = None
        self.tgaz_cache: Dict[str, Optional[Tuple[float, float]]] = {}
        self.tgaz_cache_lock = threading.Lock()
        self.tgaz_cache_path: Optional[str] = None
        self.tgaz_cache_last_save_ts = 0.0
        self.tgaz_rl_lock = threading.Lock()
        self.tgaz_last_req_ts = 0.0
        self.llm_client: Optional[StoryAgentLLM] = None
        self.llm_lock = threading.Lock()
        self.split_cache: Dict[str, Tuple[str, str]] = {}
        self.split_cache_lock = threading.Lock()

    def get_llm_client(self, event_callback: Optional[callable] = None) -> StoryAgentLLM:
        if event_callback:
            return StoryAgentLLM(event_callback=event_callback)
        if self.llm_client is None:
            with self.llm_lock:
                if self.llm_client is None:
                    self.llm_client = StoryAgentLLM()
        return self.llm_client

    def load_tgaz_cache(self) -> None:
        self.tgaz_cache_path = _resolve_tgaz_cache_path()
        p = self.tgaz_cache_path
        if not p or not os.path.exists(p):
            return
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        with self.tgaz_cache_lock:
            for key, value in data.items():
                if not isinstance(key, str):
                    continue
                if value is None:
                    self.tgaz_cache[key] = None
                    continue
                if isinstance(value, list) and len(value) >= 2:
                    try:
                        lat = float(value[0])
                        lon = float(value[1])
                    except Exception:
                        continue
                    self.tgaz_cache[key] = (lat, lon)

    def save_tgaz_cache(self, force: bool = False) -> None:
        p = self.tgaz_cache_path or _resolve_tgaz_cache_path()
        if not p:
            return
        now = time.time()
        if (not force) and (now - self.tgaz_cache_last_save_ts < 2.0):
            return
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with self.tgaz_cache_lock:
                data = {k: (None if v is None else [float(v[0]), float(v[1])]) for k, v in self.tgaz_cache.items()}
            Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.tgaz_cache_last_save_ts = now
        except Exception:
            return

    def tgaz_rate_limit(self) -> None:
        min_interval = float(os.getenv("MAP_STORY_TGAZ_MIN_INTERVAL", "1.1"))
        if min_interval <= 0:
            return
        with self.tgaz_rl_lock:
            now = time.monotonic()
            wait = (self.tgaz_last_req_ts + min_interval) - now
            if wait > 0:
                time.sleep(wait)
            self.tgaz_last_req_ts = time.monotonic()

    def load_historical_index(self) -> Dict[str, Tuple[float, float]]:
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

    def load_place_aliases(self) -> Dict[str, List[Dict[str, object]]]:
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
        alias_map: Dict[str, List[Dict[str, object]]] = {}
        name_index: Dict[str, List[str]] = {}
        for alias, value in raw.items():
            norm_alias = normalize_place_key(alias)
            if not norm_alias:
                continue
            entry: Dict[str, object] = {"names": [], "_key": alias}
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
                dynasty_raw = value.get("dynasty")
                if isinstance(dynasty_raw, str) and dynasty_raw.strip():
                    entry["dynasty"] = dynasty_raw.strip()
            if not entry.get("names") and not entry.get("coords"):
                continue
            # ── 支持同名键碰撞 ──
            if norm_alias not in alias_map:
                alias_map[norm_alias] = []
            alias_map[norm_alias].append(entry)
            # ── 构建反向索引 ──
            index_keys = set()
            index_keys.add(norm_alias)
            for name in entry.get("names") or []:
                name_norm = normalize_place_key(str(name))
                if name_norm:
                    index_keys.add(name_norm)
            for ik in index_keys:
                if ik not in name_index:
                    name_index[ik] = []
                if norm_alias not in name_index[ik]:
                    name_index[ik].append(norm_alias)
        self.place_name_index = name_index
        return alias_map


_state = _GeocodeState()
_HISTORICAL_INDEX = _state.historical_index
_HISTORICAL_INDEX_LOCK = _state.historical_index_lock
_PLACE_ALIASES = _state.place_aliases
_PLACE_ALIASES_LOCK = _state.place_aliases_lock


def _sync_legacy_place_state() -> None:
    global _HISTORICAL_INDEX, _PLACE_ALIASES
    _HISTORICAL_INDEX = _state.historical_index
    _PLACE_ALIASES = _state.place_aliases


def _apply_legacy_place_state() -> None:
    _state.historical_index = _HISTORICAL_INDEX
    _state.place_aliases = _PLACE_ALIASES


def _get_llm_client(event_callback: Optional[callable] = None) -> StoryAgentLLM:
    return _state.get_llm_client(event_callback=event_callback)


def normalize_place_key(text: str) -> str:
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[\s\t\r\n]+", "", s)
    s = re.sub(r"[（(].*?[）)]", "", s)
    s = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", s)
    s = re.sub(r"(一带|附近|周边|地区|境内|境外|等地|之地|左右|一线)$", "", s)
    return s.strip()


_PLACE_REJECT_KEYS = {normalize_place_key(item) for item in (BANNED_PLACE_KEYS | _PLACE_REJECT_EXACT) if item}


def _is_geocodeable_place_name(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw in _PLACE_REJECT_EXACT:
        return False
    if any(pattern.search(raw) for pattern in _PLACE_REJECT_PATTERNS):
        return False
    norm = normalize_place_key(raw)
    if not norm:
        return False
    if norm in _PLACE_REJECT_KEYS:
        return False
    return True


def _resolve_tgaz_cache_path() -> str:
    p = (os.getenv("MAP_STORY_TGAZ_CACHE") or "").strip()
    if p:
        return os.path.abspath(os.path.expanduser(p))
    return os.path.join(project_root_path(), ".cache", "story_map_tgaz_cache.json")


def _place_alias_candidates() -> List[str]:
    env_path = os.getenv("MAP_STORY_state.place_aliases", "").strip()
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    repo_root = project_root_path()
    candidates.extend(
        [
            os.path.join(repo_root, "data", "corpus", "place_aliases.json"),
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

    alias_map: Dict[str, List[Dict[str, object]]] = {}
    name_index: Dict[str, List[str]] = {}
    for alias, value in raw.items():
        norm_alias = normalize_place_key(alias)
        if not norm_alias:
            continue
        entry: Dict[str, object] = {"names": [], "_key": alias}  # 保留原始 key 用于调试
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
            dynasty_raw = value.get("dynasty")
            if isinstance(dynasty_raw, str) and dynasty_raw.strip():
                entry["dynasty"] = dynasty_raw.strip()
        if not entry.get("names") and not entry.get("coords"):
            continue
        # ── 支持同名键碰撞：同一归一化键可对应多个条目（如"东京"对应宋代开封和日本东京）──
        if norm_alias not in alias_map:
            alias_map[norm_alias] = []
        alias_map[norm_alias].append(entry)

        # ── 构建反向索引：name → [匹配的 alias key] ──
        # 使 "长安" 能反向查找到 "西京长安" 条目，"东京" 能查找到 "东京（宋）" 和 "东京（今日本东京都）"
        index_keys = set()
        index_keys.add(norm_alias)  # key 本身也是可搜索名
        for name in entry.get("names") or []:
            name_norm = normalize_place_key(str(name))
            if name_norm:
                index_keys.add(name_norm)
        for ik in index_keys:
            if ik not in name_index:
                name_index[ik] = []
            if norm_alias not in name_index[ik]:
                name_index[ik].append(norm_alias)

    # ── 持久化 name_index 到全局状态 ──
    _state.place_name_index = name_index
    return alias_map


def _expand_place_candidates(*names: str, dynasty: Optional[str] = None) -> Tuple[List[str], Optional[Tuple[float, float]]]:
    """展开地名候选并返回匹配的坐标。

    当 dynasty 提供时，优先返回匹配朝代的条目；无匹配朝代时回退到无朝代标注的条目。
    通过反向索引（place_name_index）支持简写地名查找，如 "长安" → "西京长安"。

    Args:
        *names: 待展开的地名候选
        dynasty: 可选，人物朝代，用于消歧（如 "宋" 的 "东京" → 开封，而非日本东京）

    Returns:
        (expanded_names, direct_coord): 展开后的候选名列表 和 直接匹配到的坐标（可为 None）
    """
    _apply_legacy_place_state()
    with _state.place_aliases_lock:
        if _state.place_aliases is None:
            _state.place_aliases = _state.load_place_aliases()
            if not _state.place_aliases:
                _state.place_aliases = _load_place_aliases()
        alias_map = _state.place_aliases or {}
        name_index = _state.place_name_index or {}
    _sync_legacy_place_state()

    # ── 辅助函数：从 alias_map 获取条目列表 ──
    def _get_entries(norm_key: str) -> List[Dict[str, object]]:
        """获取归一化键对应的所有条目（支持同名键碰撞）。"""
        entries = alias_map.get(norm_key, [])
        # 也检查反向索引中指向的其他归一化键
        for linked_key in name_index.get(norm_key, []):
            if linked_key == norm_key:
                continue
            for entry in alias_map.get(linked_key, []):
                if entry not in entries:
                    entries.append(entry)
        return entries

    # ── 辅助函数：从条目列表中按朝代优先选择最佳匹配 ──
    def _pick_best_entry(entries: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
        """按朝代优先级从条目列表中选择最佳匹配。

        优先级：
          1. 朝代精确匹配（dynasty 字段与传入 dynasty 一致）
          2. 无朝代标注（通用条目）
          3. 兜底：任意条目（即使朝代不匹配）

        Args:
            entries: 候选条目列表

        Returns:
            最佳匹配条目，列表为空时返回 None
        """
        if not entries:
            return None
        # 优先级 1：朝代精确匹配
        if dynasty:
            for entry in entries:
                if entry.get("dynasty") == dynasty:
                    return entry
        # 优先级 2：无朝代标注
        for entry in entries:
            if not entry.get("dynasty"):
                return entry
        # 优先级 3：兜底（第一个条目）
        return entries[0]

    expanded: List[str] = []
    seen_norm = set()
    queue: List[str] = [
        str(name).strip()
        for name in names
        if str(name or "").strip() and _is_geocodeable_place_name(str(name).strip())
    ]
    direct_coord: Optional[Tuple[float, float]] = None

    while queue:
        current = queue.pop(0)
        if not _is_geocodeable_place_name(current):
            _LOGGER.info("geocode_candidate_rejected stage=expand candidate=%s", current)
            continue
        norm = normalize_place_key(current)
        if not norm or norm in seen_norm:
            continue
        seen_norm.add(norm)
        expanded.append(current)
        entries = _get_entries(norm)
        entry = _pick_best_entry(entries) or {}
        coords = entry.get("coords")
        if direct_coord is None and isinstance(coords, tuple) and len(coords) >= 2:
            direct_coord = (float(coords[0]), float(coords[1]))
        for alias_name in entry.get("names") or []:
            alias_text = str(alias_name or "").strip()
            alias_norm = normalize_place_key(alias_text)
            if alias_text and alias_norm and alias_norm not in seen_norm and _is_geocodeable_place_name(alias_text):
                queue.append(alias_text)
    return expanded, direct_coord


def _load_tgaz_cache() -> None:
    _state.tgaz_cache_path = _resolve_tgaz_cache_path()
    p = _state.tgaz_cache_path
    if not p or not os.path.exists(p):
        return
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    with _state.tgaz_cache_lock:
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            if value is None:
                _state.tgaz_cache[key] = None
                continue
            if isinstance(value, list) and len(value) >= 2:
                try:
                    lat = float(value[0])
                    lon = float(value[1])
                except Exception:
                    continue
                _state.tgaz_cache[key] = (lat, lon)


def _save_tgaz_cache(force: bool = False) -> None:
    p = _state.tgaz_cache_path or _resolve_tgaz_cache_path()
    if not p:
        return
    now = time.time()
    if (not force) and (now - _state.tgaz_cache_last_save_ts < 2.0):
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _state.tgaz_cache_lock:
            data = {k: (None if v is None else [float(v[0]), float(v[1])]) for k, v in _state.tgaz_cache.items()}
        Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _state.tgaz_cache_last_save_ts = now
    except Exception:
        return


def _tgaz_rate_limit() -> None:
    min_interval = float(os.getenv("MAP_STORY_TGAZ_MIN_INTERVAL", "1.1"))
    if min_interval <= 0:
        return
    with _state.tgaz_rl_lock:
        now = time.monotonic()
        wait = (_state.tgaz_last_req_ts + min_interval) - now
        if wait > 0:
            time.sleep(wait)
        _state.tgaz_last_req_ts = time.monotonic()


def _historical_index_candidates() -> List[str]:
    env_path = os.getenv("HISTORICAL_PLACES_INDEX", "").strip()
    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = project_root_path()
    candidates.extend(
        [
            os.path.join(here, "historical_places_index.jsonl"),
            os.path.join(here, "..", "historical_places_index.jsonl"),
            os.path.join(here, "..", "..", "historical_places_index.jsonl"),
            os.path.join(here, "..", "..", "..", "historical_places_index.jsonl"),
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


def lookup_coords_from_historical_index(*names: str, dynasty: Optional[str] = None) -> Optional[Tuple[float, float]]:
    _apply_legacy_place_state()
    expanded_names, direct_coord = _expand_place_candidates(*names, dynasty=dynasty)
    if direct_coord:
        return direct_coord
    with _state.historical_index_lock:
        if _state.historical_index is None:
            _state.historical_index = _state.load_historical_index()
        mapping = _state.historical_index or {}
    _sync_legacy_place_state()
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
    with _state.tgaz_cache_lock:
        if cache_key in _state.tgaz_cache:
            return _state.tgaz_cache[cache_key]
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
        with _state.tgaz_cache_lock:
            _state.tgaz_cache[cache_key] = None
        _save_tgaz_cache(force=False)
        return None
    items = data.get("placenames") if isinstance(data, dict) else None
    if not isinstance(items, list):
        with _state.tgaz_cache_lock:
            _state.tgaz_cache[cache_key] = None
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
    with _state.tgaz_cache_lock:
        _state.tgaz_cache[cache_key] = best
    _save_tgaz_cache(force=False)
    return best


def _strip_place_metadata(name: str) -> List[str]:
    """把 '206年: 洛阳 (入仕)' / '约公元前 200 年 — 关中' 之类复合 key 拆出候选。

    render 管线里 dataset 的 place 字段经常带年份和事件说明,例如::

        "206年: 洛阳 (入仕)"
        "230年—234年: 关中 (抵御北伐)"
        "约公元前 221 年 · 咸阳 (秦并天下)"

    直接喂给 geocode 会让 _looks_chinese 通过,但 _is_geocodeable_place_name
    拒绝,_expand_place_candidates 就丢弃掉,最终落到 backup 链路 (Nominatim)
    拿到欧洲坐标。

    这里把年份前缀 + 事件后缀剥掉,产生多个候选: '洛阳'、 '关中'、 '咸阳' 等。
    """
    text = str(name or "").strip()
    if not text:
        return []
    cands: List[str] = []
    # 拆 "年—" / "年-" / "年·" / "年:" / "年 ~" 几种连接符
    parts = re.split(r"[—\-~:：·]+", text)
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        # 去掉括号事件后缀: "洛阳 (入仕)" -> "洛阳"
        m = re.match(r"^(.*?)(?:\s*[（(][^()]*[)）]\s*)$", p)
        if m:
            core = m.group(1).strip()
            if core:
                p = core
        # 去掉年份词头: "206年" / "约公元前 200 年" / "BC 50"
        cleaned = re.sub(
            r"^(?:约|大约|约于)?\s*(?:公元前|公元|BC|B\.C\.|CE|BCE)?\s*\d{1,4}\s*年?\s*",
            "",
            p,
        ).strip()
        if cleaned:
            cands.append(cleaned)
        else:
            cands.append(p)
    seen = set()
    out: List[str] = []
    for c in cands:
        n = normalize_place_key(c)
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(c)
    return out


def _accept_china_coord(candidates: List[str], coord: Optional[Tuple[float, float]]) -> bool:
    """硬校验:中文地名必须落在中国境内坐标。

    为什么需要这个:
    - ``_expand_place_candidates`` / ``_tgaz_query`` / Nominatim 等链路
      在中英混跑时,可能把 ``许昌`` 错配成意大利/西班牙/巴西某城市
      (因为英文转写 + 模糊匹配命中海外同名/误识)
    - ``geocode_city`` 内部已经把 ``_looks_chinese`` + AMap 主选路径处理掉了
    - 在 render 管线里 ``resolve_place_coord`` 的多个早期返回路径并
      没有这套闸门,会让错配坐标直接进 HTML

    判定:
    - 任一候选是中文/古地名 -> 坐标必须在中国境内
    - 所有候选都非中文 (像 John Snow -> York) -> 不强制,接受任何 (lat, lng)
    - 任一候选命中 _looks_foreign_location (e.g. 含国名/古罗马地名字样) -> 不强制
    """
    if not coord:
        return True
    expanded_names, _direct_coord = _expand_place_candidates(*candidates)
    all_candidates = [c for c in [*candidates, *expanded_names] if c]
    has_chinese_hint = any(_looks_chinese(c) for c in all_candidates)
    has_foreign_hint = any(_looks_foreign_location(c) or re.search(r"[A-Za-z]", str(c or "")) for c in all_candidates)
    if not has_chinese_hint or has_foreign_hint:
        return True
    lat, lng = coord
    if not _is_inside_china_mainland(lat, lng):
        _LOGGER.warning(
            "resolve_place_coord: rejected out-of-China coord candidates=%s -> (%.4f, %.4f)",
            [c for c in candidates if c], float(lat), float(lng),
        )
        return False
    return True


def resolve_place_coord(place: str, year: Optional[int] = None, *aliases: str, dynasty: Optional[str] = None) -> Optional[Tuple[float, float]]:
    candidates = [place] + [alias for alias in aliases if alias]
    direct_expanded_names, direct_coord = _expand_place_candidates(*candidates, dynasty=dynasty)
    if direct_coord and _accept_china_coord(candidates, direct_coord):
        return direct_coord
    # 把 "206年: 洛阳 (入仕)" 之类的复合 key 拆出原始地名候选
    cleaned_candidates: List[str] = []
    for c in candidates:
        cleaned_candidates.extend(_strip_place_metadata(c))
    if cleaned_candidates:
        candidates = candidates + cleaned_candidates
    expanded_names, direct_coord = _expand_place_candidates(*candidates, dynasty=dynasty)
    if direct_coord and _accept_china_coord(candidates, direct_coord):
        return direct_coord
    if len(expanded_names) <= len(direct_expanded_names) and direct_expanded_names:
        expanded_names = direct_expanded_names
    coord = lookup_coords_from_historical_index(*expanded_names, dynasty=dynasty)
    if coord and _accept_china_coord(candidates, coord):
        return coord
    for cand in expanded_names:
        coord = _tgaz_query(cand, year)
        if coord and _accept_china_coord(candidates, coord):
            return coord
    for cand in expanded_names:
        try:
            coord = geocode_city(cand)
        except Exception:
            continue
        if coord and _accept_china_coord(candidates, coord):
            return coord
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
    with _state.split_cache_lock:
        pending = [text for text in ordered if text not in _state.split_cache]
    if not pending:
        with _state.split_cache_lock:
            return {text: _state.split_cache[text] for text in ordered if text in _state.split_cache}
    use_llm = str(os.getenv("STORY_MAP_ENABLE_LLM_SPLIT", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
    if not use_llm:
        with _state.split_cache_lock:
            for text in pending:
                if text in _state.split_cache:
                    continue
                _state.split_cache[text] = split_ancient_modern_heuristic(text)
            return {text: _state.split_cache.get(text, ("", "")) for text in ordered}
    try:
        client = _get_llm_client(event_callback=event_callback)
    except Exception as exc:
        _LOGGER.warning("LLM 客户端初始化失败，回退至启发式拆解逻辑: %s", exc)
        with _state.split_cache_lock:
            for text in pending:
                if text in _state.split_cache:
                    continue
                _state.split_cache[text] = split_ancient_modern_heuristic(text)
            return {text: _state.split_cache.get(text, ("", "")) for text in ordered}
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
        with _state.split_cache_lock:
            for text in chunk:
                if text in _state.split_cache:
                    continue
                _state.split_cache[text] = mapping.get(text) or ("", "")
    with _state.split_cache_lock:
        return {text: _state.split_cache.get(text, ("", "")) for text in ordered}


def split_ancient_modern(
    loc_text: str,
    event_callback: Optional[callable] = None,
) -> Tuple[str, str]:
    if not loc_text:
        return "", ""
    with _state.split_cache_lock:
        cached = _state.split_cache.get(loc_text)
    if cached:
        return cached
    use_llm = str(os.getenv("STORY_MAP_ENABLE_LLM_SPLIT", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
    if not use_llm:
        result = split_ancient_modern_heuristic(loc_text)
        with _state.split_cache_lock:
            _state.split_cache[loc_text] = result
        return result
    try:
        client = _get_llm_client(event_callback=event_callback)
    except Exception as exc:
        _LOGGER.warning("LLM 客户端初始化失败，回退至启发式拆解逻辑: %s", exc)
        result = split_ancient_modern_heuristic(loc_text)
        with _state.split_cache_lock:
            _state.split_cache[loc_text] = result
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
    with _state.split_cache_lock:
        _state.split_cache[loc_text] = result
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
        if not norm_key or norm_key in BANNED_PLACE_KEYS or len(norm_key) < 2:
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
