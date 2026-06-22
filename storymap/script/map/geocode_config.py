from __future__ import annotations

import os


def env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)) or str(default)))
    except Exception:
        return max(1, int(default))


def env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)) or str(default))
    except Exception:
        value = float(default)
    return max(float(minimum), value)


def geocode_negative_cache_ttl() -> int:
    return env_int("MAP_STORY_GEOCODE_NEGATIVE_CACHE_TTL", 300)


def fetch_timeout_seconds() -> int:
    return env_int("MAP_STORY_GEOCODE_FETCH_TIMEOUT", 16)


def nominatim_timeout_seconds() -> int:
    return env_int("MAP_STORY_GEOCODE_NOMINATIM_TIMEOUT", fetch_timeout_seconds())


def amap_timeout_seconds() -> int:
    return env_int("MAP_STORY_AMAP_TIMEOUT", 12)


def monid_timeout_seconds() -> int:
    return env_int("MAP_STORY_MONID_TIMEOUT", 20)


def first_non_empty_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def monid_api_key() -> str:
    return first_non_empty_env("MONID_API_KEY", "MAP_STORY_MONID_API_KEY")


def monid_geocode_enabled() -> bool:
    override = os.getenv("MAP_STORY_MONID_GEOCODE_ENABLED")
    if override is not None and str(override).strip():
        return str(override).strip().lower() in {"1", "true", "yes", "on"}
    return bool(monid_api_key())


def geocode_min_interval_seconds() -> float:
    return env_float("MAP_STORY_GEOCODE_MIN_INTERVAL", 1.1)


def amap_min_interval_seconds() -> float:
    return env_float("MAP_STORY_AMAP_MIN_INTERVAL", 0.12)
