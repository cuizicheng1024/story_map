from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Dict, Optional


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_memory_cache_path() -> str:
    path = (os.getenv("STORY_AGENT_MEMORY_CACHE") or "").strip()
    if path:
        return os.path.abspath(os.path.expanduser(path))
    return os.path.join(_project_root(), ".cache", "story_agent_memory.json")


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
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = os.path.abspath(os.path.expanduser(path or resolve_memory_cache_path()))
        self._lock = threading.RLock()
        self._loaded = False
        self._data: Dict[str, object] = {
            "version": 1,
            "people": {},
            "places": {},
        }

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
            people = payload.get("people")
            places = payload.get("places")
            if isinstance(people, dict):
                self._data["people"] = people
            if isinstance(places, dict):
                self._data["places"] = places

    def _save(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)

    def get_person_search(self, person: str) -> Optional[Dict[str, object]]:
        key = str(person or "").strip()
        if not key:
            return None
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.get("people")
            if not isinstance(bucket, dict):
                return None
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return None
            value = entry.get("search_result")
            return dict(value) if isinstance(value, dict) else None

    def set_person_search(self, person: str, search_result: Dict[str, object]) -> None:
        key = str(person or "").strip()
        if not key or not isinstance(search_result, dict):
            return
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.setdefault("people", {})
            if not isinstance(bucket, dict):
                return
            record = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
            record = dict(record or {})
            record["search_result"] = dict(search_result)
            record["updated_at"] = _now_ts()
            bucket[key] = record
        self._save()

    def get_place_map(self, place_name: str) -> Optional[Dict[str, object]]:
        key = _normalize_place_key(str(place_name or ""))
        if not key:
            return None
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.get("places")
            if not isinstance(bucket, dict):
                return None
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return None
            value = entry.get("place_map")
            return dict(value) if isinstance(value, dict) else None

    def set_place_map(self, place_name: str, place_map: Dict[str, object]) -> None:
        key = _normalize_place_key(str(place_name or ""))
        if not key or not isinstance(place_map, dict):
            return
        self._ensure_loaded()
        with self._lock:
            bucket = self._data.setdefault("places", {})
            if not isinstance(bucket, dict):
                return
            record = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
            record = dict(record or {})
            record["place_map"] = dict(place_map)
            record["updated_at"] = _now_ts()
            bucket[key] = record
        self._save()


_DEFAULT_STORE: Optional[StoryAgentMemoryStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_memory_store() -> StoryAgentMemoryStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = StoryAgentMemoryStore()
        return _DEFAULT_STORE


__all__ = [
    "StoryAgentMemoryStore",
    "get_default_memory_store",
    "resolve_memory_cache_path",
]
