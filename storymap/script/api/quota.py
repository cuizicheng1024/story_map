"""生成配额与幂等性控制模块。

提供每日生成额度限制和请求幂等性去重，用于防止 API 滥用和重复提交。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path

from ..core.persistence import SafeJSONStore

_GENERATE_DAILY_LIMIT_ENV_KEYS = ("MAP_STORY_GENERATE_DAILY_LIMIT", "STORY_MAP_GENERATE_DAILY_LIMIT")
_GENERATE_DAILY_LIMIT_PATH_ENV_KEYS = (
    "MAP_STORY_GENERATE_DAILY_LIMIT_PATH",
    "STORY_MAP_GENERATE_DAILY_LIMIT_PATH",
)
_GENERATE_IDEMPOTENCY_PATH_ENV_KEYS = (
    "MAP_STORY_GENERATE_IDEMPOTENCY_PATH",
    "STORY_MAP_GENERATE_IDEMPOTENCY_PATH",
)
_GENERATE_IDEMPOTENCY_TTL_ENV_KEYS = (
    "MAP_STORY_GENERATE_IDEMPOTENCY_TTL_SECONDS",
    "STORY_MAP_GENERATE_IDEMPOTENCY_TTL_SECONDS",
)
_GENERATE_IDEMPOTENCY_HEADER_KEYS = ("x-idempotency-key", "idempotency-key")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_GENERATE_DAILY_LIMIT_PATH = _REPO_ROOT / "artifacts" / "runtime" / "generate_daily_quota.json"
_DEFAULT_GENERATE_IDEMPOTENCY_PATH = _REPO_ROOT / "artifacts" / "runtime" / "generate_idempotency.json"


def _first_env(*keys: str) -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return ""


# ── 每日配额 ─────────────────────────────────────────────────────────────

class GenerateDailyQuotaStore(SafeJSONStore):
    def __init__(self, target_path: Path) -> None:
        super().__init__(target_path)

    def consume(self, bucket: str, limit: int) -> dict:
        if limit <= 0:
            return {"allowed": True, "limit": 0, "used": 0, "remaining": None, "reset_on": date.today().isoformat()}
        bucket_key = str(bucket or "").strip() or "unknown"
        today = date.today().isoformat()
        with self._lock:
            payload = self._load()
            if str(payload.get("date") or "") != today:
                payload = {"date": today, "counters": {}}
            counters = payload.get("counters")
            if not isinstance(counters, dict):
                counters = {}
                payload["counters"] = counters
            used = int(counters.get(bucket_key) or 0)
            if used >= limit:
                return {"allowed": False, "limit": limit, "used": used, "remaining": 0, "reset_on": today}
            counters[bucket_key] = used + 1
            self._save(payload)
            return {
                "allowed": True,
                "limit": limit,
                "used": used + 1,
                "remaining": max(0, limit - used - 1),
                "reset_on": today,
            }


_DAILY_QUOTA_STORES: dict[str, GenerateDailyQuotaStore] = {}


def daily_limit_from_env() -> int:
    raw = _first_env(*_GENERATE_DAILY_LIMIT_ENV_KEYS)
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _daily_limit_path() -> Path:
    raw = _first_env(*_GENERATE_DAILY_LIMIT_PATH_ENV_KEYS)
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_GENERATE_DAILY_LIMIT_PATH


def get_daily_quota_store() -> GenerateDailyQuotaStore:
    path = str(_daily_limit_path())
    store = _DAILY_QUOTA_STORES.get(path)
    if store is None:
        store = GenerateDailyQuotaStore(Path(path))
        _DAILY_QUOTA_STORES[path] = store
    return store


# ── 幂等性去重 ────────────────────────────────────────────────────────────

class GenerateIdempotencyStore(SafeJSONStore):
    def __init__(self, target_path: Path, *, ttl_seconds: int) -> None:
        super().__init__(target_path)
        self._ttl_seconds = max(int(ttl_seconds), 60)

    def lookup(self, idempotency_key: str) -> dict:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return {}
        now = time.time()
        with self._lock:
            payload = self._prune_locked(self._load(), now=now, ttl_seconds=self._ttl_seconds)
            entry = payload.get("entries", {}).get(normalized)
            self._save(payload)
        return dict(entry or {}) if isinstance(entry, dict) else {}

    def remember(self, idempotency_key: str, *, task_id: str, text: str, bucket: str) -> None:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return
        now = time.time()
        with self._lock:
            payload = self._prune_locked(self._load(), now=now, ttl_seconds=self._ttl_seconds)
            entries = payload.get("entries")
            if not isinstance(entries, dict):
                entries = {}
                payload["entries"] = entries
            entries[normalized] = {
                "task_id": str(task_id or "").strip(),
                "text": str(text or "").strip(),
                "bucket": str(bucket or "").strip(),
                "created_at": now,
            }
            self._save(payload)

    @staticmethod
    def _prune_locked(payload: dict, *, now: float, ttl_seconds: int) -> dict:
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        fresh = {}
        for key, item in entries.items():
            if not isinstance(item, dict):
                continue
            created_at = float(item.get("created_at") or 0.0)
            if created_at > 0 and (now - created_at) > ttl_seconds:
                continue
            fresh[str(key)] = item
        payload["entries"] = fresh
        return payload


_IDEMPOTENCY_STORES: dict[str, GenerateIdempotencyStore] = {}


def idempotency_ttl_seconds_from_env() -> int:
    raw = _first_env(*_GENERATE_IDEMPOTENCY_TTL_ENV_KEYS)
    if not raw:
        return 6 * 3600
    try:
        return max(60, int(raw))
    except ValueError:
        return 6 * 3600


def _idempotency_path() -> Path:
    raw = _first_env(*_GENERATE_IDEMPOTENCY_PATH_ENV_KEYS)
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_GENERATE_IDEMPOTENCY_PATH


def get_idempotency_store() -> GenerateIdempotencyStore:
    path = str(_idempotency_path())
    store = _IDEMPOTENCY_STORES.get(path)
    if store is None:
        store = GenerateIdempotencyStore(Path(path), ttl_seconds=idempotency_ttl_seconds_from_env())
        _IDEMPOTENCY_STORES[path] = store
    return store


# ── 请求工具 ──────────────────────────────────────────────────────────────

def request_client_host(request: object) -> str:
    forwarded = str(getattr(request, "headers", {}).get("x-forwarded-for") or "").split(",")[0].strip()
    real_ip = str(getattr(request, "headers", {}).get("x-real-ip") or "").strip()
    client_host = str(getattr(getattr(request, "client", None), "host", "") or "").strip()
    return forwarded or real_ip or client_host or ""


def request_client_bucket(request: object) -> str:
    return request_client_host(request) or "unknown"


def request_idempotency_key(request: object, body: object) -> str:
    headers = getattr(request, "headers", {})
    for header_name in _GENERATE_IDEMPOTENCY_HEADER_KEYS:
        value = str(headers.get(header_name) or "").strip()
        if value:
            return value[:256]
    if isinstance(body, dict):
        value = str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip()
        if value:
            return value[:256]
    return ""


__all__ = [
    "daily_limit_from_env",
    "GenerateDailyQuotaStore",
    "GenerateIdempotencyStore",
    "get_daily_quota_store",
    "get_idempotency_store",
    "request_client_bucket",
    "request_idempotency_key",
]
