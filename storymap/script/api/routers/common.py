from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, Request as FastAPIRequest

_RUNTIME_DEBUG_TOKEN_ENV_KEYS = ("STORYMAP_RUNTIME_DEBUG_TOKEN", "MAP_STORY_RUNTIME_DEBUG_TOKEN")
_RUNTIME_DEBUG_TOKEN_HEADER_KEYS = ("x-storymap-debug-token", "x-runtime-debug-token")
_DEBUG_EVENT_LOCK = threading.Lock()


def _first_env(*keys: str) -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return ""


def _origin_matches_request_host(origin: str, request: FastAPIRequest) -> bool:
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    origin_host = str(parsed.netloc or "").strip().lower()
    request_host = str(request.headers.get("host", "") or "").strip().lower()
    if not origin_host or not request_host:
        return False
    if origin_host == request_host:
        return True
    return origin_host.split(":", 1)[0] == request_host.split(":", 1)[0]


def enforce_origin(request: FastAPIRequest, resolve_cors_origin) -> None:
    origin = str(request.headers.get("origin", "") or "").strip()
    if origin.lower() == "null":
        origin = ""
    if origin and not (resolve_cors_origin(origin) or _origin_matches_request_host(origin, request)):
        raise HTTPException(status_code=403, detail="origin not allowed")


def runtime_debug_token() -> str:
    return _first_env(*_RUNTIME_DEBUG_TOKEN_ENV_KEYS)


def has_runtime_debug_token(request: FastAPIRequest) -> bool:
    expected = runtime_debug_token()
    if not expected:
        return False
    for header_name in _RUNTIME_DEBUG_TOKEN_HEADER_KEYS:
        value = str(request.headers.get(header_name) or "").strip()
        if value and secrets.compare_digest(value, expected):
            return True
    return False


def enforce_runtime_debug_access(request: FastAPIRequest) -> None:
    if has_runtime_debug_token(request):
        return
    raise HTTPException(status_code=403, detail="runtime debug access denied")


def sanitize_debug_session_id(raw: object) -> str:
    text = str(raw or "").strip().lower()
    filtered = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in text)
    filtered = "-".join(part for part in filtered.split("-") if part)
    return filtered[:80] or "default"


def debug_log_file(session_id: object) -> Path:
    safe_session = sanitize_debug_session_id(session_id)
    dbg_dir = Path(".dbg")
    dbg_dir.mkdir(parents=True, exist_ok=True)
    return dbg_dir / f"trae-debug-log-{safe_session}.ndjson"


def append_debug_event(payload: object, request: FastAPIRequest) -> dict:
    item = dict(payload or {}) if isinstance(payload, dict) else {}
    session_id = sanitize_debug_session_id(item.get("sessionId"))
    event = {
        "sessionId": session_id,
        "runId": str(item.get("runId") or "").strip() or "pre-fix",
        "hypothesisId": str(item.get("hypothesisId") or "").strip() or "U",
        "location": str(item.get("location") or "").strip(),
        "msg": str(item.get("msg") or "").strip(),
        "data": dict(item.get("data") or {}) if isinstance(item.get("data"), dict) else {},
        "ts": int(item.get("ts") or int(time.time() * 1000)),
        "origin": str(request.headers.get("origin") or "").strip(),
        "referer": str(request.headers.get("referer") or "").strip(),
        "userAgent": str(request.headers.get("user-agent") or "").strip(),
    }
    target = debug_log_file(session_id)
    with _DEBUG_EVENT_LOCK:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_debug_events(session_id: object, *, last: int = 50) -> list[dict]:
    target = debug_log_file(session_id)
    if not target.exists():
        return []
    lines = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    if last > 0:
        lines = lines[-last:]
    items: list[dict] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items
