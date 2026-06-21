from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Dict, List, Optional


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


DEFAULT_MEMORY_SCHEMA_VERSION = 2
DEFAULT_MEMORY_TTL_SECONDS = 7 * 24 * 60 * 60


def resolve_memory_cache_path() -> str:
    path = (os.getenv("STORY_AGENT_MEMORY_CACHE") or "").strip()
    if path:
        return os.path.abspath(os.path.expanduser(path))
    return os.path.join(_project_root(), ".cache", "story_agent_memory.json")


def resolve_memory_ttl_seconds() -> int:
    raw = (os.getenv("STORY_AGENT_MEMORY_TTL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_MEMORY_TTL_SECONDS
    try:
        return max(0, int(raw))
    except Exception:
        return DEFAULT_MEMORY_TTL_SECONDS


def _now_ts() -> float:
    return float(time.time())


def _normalize_place_key(text: str) -> str:
    content = str(text or "").strip().lower()
    if not content:
        return ""
    content = re.sub(r"[\s\t\r\n]+", "", content)
    content = re.sub(r"[（(].*?[）)]", "", content)
    content = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", content)
    content = re.sub(r"(一带|附近|周边|地区|境内|境外|等地|之地|左右|一线)$", "", content)
    return content.strip()


class StoryAgentMemoryStore:
    def __init__(
        self,
        path: Optional[str] = None,
        *,
        ttl_seconds: Optional[int] = None,
        schema_version: int = DEFAULT_MEMORY_SCHEMA_VERSION,
    ) -> None:
        self.path = os.path.abspath(os.path.expanduser(path or resolve_memory_cache_path()))
        self.ttl_seconds = resolve_memory_ttl_seconds() if ttl_seconds is None else max(0, int(ttl_seconds))
        self.schema_version = max(1, int(schema_version))
        self._lock = threading.RLock()
        self._loaded = False
        self._data: Dict[str, object] = self._empty_payload()

    def _empty_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "people": {},
            "places": {},
        }

    def _schema_version_from_payload(self, payload: object) -> int:
        if not isinstance(payload, dict):
            return 0
        raw = payload.get("schema_version", payload.get("version"))
        try:
            return int(raw or 0)
        except Exception:
            return 0

    def _entry_expired(self, entry: object) -> bool:
        if self.ttl_seconds <= 0:
            return False
        if not isinstance(entry, dict):
            return True
        try:
            updated_at = float(entry.get("updated_at") or 0)
        except Exception:
            return True
        if updated_at <= 0:
            return True
        return (_now_ts() - updated_at) > self.ttl_seconds

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            if self._schema_version_from_payload(payload) != self.schema_version:
                return
            people = payload.get("people")
            places = payload.get("places")
            if isinstance(people, dict):
                self._data["people"] = people
            if isinstance(places, dict):
                self._data["places"] = places

    def _save(self) -> None:
        with self._lock:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._data["schema_version"] = self.schema_version
            # 用 pid 区分临时文件，避免多进程共享同一缓存文件时互相覆盖 tmp。
            tmp_path = f"{self.path}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)

    def _read_bucket_entry(self, bucket_name: str, key: str, value_field: str) -> Optional[Dict[str, object]]:
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.get(bucket_name)
            if not isinstance(bucket, dict):
                return None
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return None
            if self._entry_expired(entry):
                bucket.pop(key, None)
                self._save()
                return None
            value = entry.get(value_field)
            return dict(value) if isinstance(value, dict) else None

    def _write_bucket_entry(self, bucket_name: str, key: str, value_field: str, value: Dict[str, object]) -> None:
        if not key or not isinstance(value, dict):
            return
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.setdefault(bucket_name, {})
            if not isinstance(bucket, dict):
                return
            record = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
            record = dict(record or {})
            record[value_field] = dict(value)
            record["updated_at"] = _now_ts()
            bucket[key] = record
        self._save()

    def _invalidate_bucket_entry(self, bucket_name: str, key: str) -> bool:
        if not key:
            return False
        self._ensure_loaded()
        removed = False
        with self._lock:
            bucket = self._data.get(bucket_name)
            if not isinstance(bucket, dict):
                return False
            removed = key in bucket
            if removed:
                bucket.pop(key, None)
        if removed:
            self._save()
        return removed

    def get_person_search(self, person: str) -> Optional[Dict[str, object]]:
        key = str(person or "").strip()
        if not key:
            return None
        return self._read_bucket_entry("people", key, "search_result")

    def set_person_search(self, person: str, search_result: Dict[str, object]) -> None:
        key = str(person or "").strip()
        self._write_bucket_entry("people", key, "search_result", search_result)

    def get_place_map(self, place_name: str) -> Optional[Dict[str, object]]:
        key = _normalize_place_key(str(place_name or ""))
        if not key:
            return None
        return self._read_bucket_entry("places", key, "place_map")

    def set_place_map(self, place_name: str, place_map: Dict[str, object]) -> None:
        key = _normalize_place_key(str(place_name or ""))
        self._write_bucket_entry("places", key, "place_map", place_map)

    def invalidate_person_search(self, person: str) -> bool:
        key = str(person or "").strip()
        return self._invalidate_bucket_entry("people", key)

    def invalidate_place_map(self, place_name: str) -> bool:
        key = _normalize_place_key(str(place_name or ""))
        return self._invalidate_bucket_entry("places", key)

    def invalidate_all(self, bucket: str = "") -> int:
        self._ensure_loaded()
        removed = 0
        bucket_names: List[str]
        normalized_bucket = str(bucket or "").strip().lower()
        if normalized_bucket == "people":
            bucket_names = ["people"]
        elif normalized_bucket in {"places", "place_map"}:
            bucket_names = ["places"]
        else:
            bucket_names = ["people", "places"]
        with self._lock:
            for bucket_name in bucket_names:
                current = self._data.get(bucket_name)
                if not isinstance(current, dict):
                    continue
                removed += len(current)
                self._data[bucket_name] = {}
        if removed:
            self._save()
        return removed


_DEFAULT_STORE: Optional[StoryAgentMemoryStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_memory_store() -> StoryAgentMemoryStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = StoryAgentMemoryStore()
        return _DEFAULT_STORE


__all__ = [
    "DEFAULT_MEMORY_SCHEMA_VERSION",
    "DEFAULT_MEMORY_TTL_SECONDS",
    "StoryAgentMemoryStore",
    "get_default_memory_store",
    "resolve_memory_cache_path",
    "resolve_memory_ttl_seconds",
]
