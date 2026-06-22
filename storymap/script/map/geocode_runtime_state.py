from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional, Tuple


def record_metric(metrics: Dict[str, int], key: str, amount: int = 1) -> None:
    metrics[key] = int(metrics.get(key, 0)) + int(amount)


def build_metrics_snapshot(metrics: Dict[str, int], *, negative_cache_size: int) -> Dict[str, object]:
    snapshot = {key: int(value) for key, value in metrics.items()}
    lookups = max(1, snapshot.get("lookups", 0))
    provider_requests = (
        snapshot.get("amap_requests", 0)
        + snapshot.get("monid_requests", 0)
        + snapshot.get("nominatim_requests", 0)
        + snapshot.get("wikidata_requests", 0)
    )
    return {
        **snapshot,
        "cache_hit_rate": round(snapshot.get("cache_hits", 0) / lookups, 4),
        "negative_cache_hit_rate": round(snapshot.get("negative_cache_hits", 0) / lookups, 4),
        "success_rate": round(snapshot.get("successes", 0) / lookups, 4),
        "timeout_rate": round(snapshot.get("timeouts", 0) / max(1, provider_requests), 4),
        "negative_cache_size": int(negative_cache_size),
    }


def reset_runtime_state(negative_cache: Dict[str, Dict[str, object]], metrics: Dict[str, int]) -> None:
    negative_cache.clear()
    for key in list(metrics.keys()):
        metrics[key] = 0


def prune_negative_cache(
    negative_cache: Dict[str, Dict[str, object]],
    *,
    now: float,
) -> bool:
    expired = [key for key, value in negative_cache.items() if float(value.get("expires_at") or 0) <= float(now)]
    for key in expired:
        negative_cache.pop(key, None)
    return bool(expired)


def negative_cache_get(
    negative_cache: Dict[str, Dict[str, object]],
    name: str,
) -> Optional[Dict[str, object]]:
    key = str(name or "").strip()
    if not key:
        return None
    item = negative_cache.get(key)
    if not isinstance(item, dict):
        return None
    return dict(item)


def negative_cache_set(
    negative_cache: Dict[str, Dict[str, object]],
    name: str,
    *,
    reason: str,
    ttl_seconds: int,
    now: float,
) -> bool:
    key = str(name or "").strip()
    if not key:
        return False
    negative_cache[key] = {
        "reason": str(reason or "failed"),
        "updated_at": float(now),
        "expires_at": float(now) + max(int(ttl_seconds), 1),
    }
    return True


def negative_cache_clear(
    negative_cache: Dict[str, Dict[str, object]],
    *names: str,
) -> bool:
    keys = [str(name or "").strip() for name in names if str(name or "").strip()]
    changed = False
    for key in keys:
        if negative_cache.pop(key, None) is not None:
            changed = True
    return changed


def load_coord_cache(
    path: str,
    *,
    is_valid_coord: Callable[[object, object], bool],
) -> Dict[str, Tuple[float, float]]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    loaded: Dict[str, Tuple[float, float]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, list) and len(value) >= 2:
            try:
                lat = float(value[0])
                lon = float(value[1])
            except Exception:
                continue
            if is_valid_coord(lat, lon):
                loaded[key] = (lat, lon)
        elif isinstance(value, dict) and "lat" in value and ("lon" in value or "lng" in value):
            try:
                lat = float(value.get("lat"))
                lon = float(value.get("lon", value.get("lng")))
            except Exception:
                continue
            if is_valid_coord(lat, lon):
                loaded[key] = (lat, lon)
    return loaded


def load_negative_cache(path: str, *, now: float) -> Dict[str, Dict[str, object]]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    loaded: Dict[str, Dict[str, object]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        expires_at = float(value.get("expires_at") or 0)
        if expires_at <= float(now):
            continue
        loaded[key] = {
            "reason": str(value.get("reason") or "failed"),
            "updated_at": float(value.get("updated_at") or now),
            "expires_at": expires_at,
        }
    return loaded


def save_coord_cache(path: str, cache: Dict[str, Tuple[float, float]]) -> bool:
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {key: [value[0], value[1]] for key, value in cache.items()}
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def save_negative_cache(path: str, negative_cache: Dict[str, Dict[str, object]], *, now: float) -> bool:
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            key: {
                "reason": str(value.get("reason") or "failed"),
                "updated_at": float(value.get("updated_at") or now),
                "expires_at": float(value.get("expires_at") or now),
            }
            for key, value in negative_cache.items()
        }
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def coord_cache_get(cache: Dict[str, Tuple[float, float]], name: str) -> Optional[Tuple[float, float]]:
    key = str(name or "").strip()
    if not key:
        return None
    return cache.get(key)


def coord_cache_set(
    cache: Dict[str, Tuple[float, float]],
    name: str,
    coord: Tuple[float, float],
) -> bool:
    key = str(name or "").strip()
    if not key or not coord:
        return False
    cache[key] = coord
    return True


__all__ = [
    "build_metrics_snapshot",
    "coord_cache_get",
    "coord_cache_set",
    "load_coord_cache",
    "load_negative_cache",
    "negative_cache_clear",
    "negative_cache_get",
    "negative_cache_set",
    "prune_negative_cache",
    "record_metric",
    "reset_runtime_state",
    "save_coord_cache",
    "save_negative_cache",
]
