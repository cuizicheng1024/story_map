from __future__ import annotations

import json
import time
from typing import Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request


def rate_limit(
    *,
    lock: object,
    get_last_request_ts: Callable[[], float],
    set_last_request_ts: Callable[[float], None],
    min_interval: float,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    if min_interval <= 0:
        return
    with lock:
        now = clock()
        wait = (get_last_request_ts() + min_interval) - now
        if wait > 0:
            sleep_fn(wait)
        set_last_request_ts(clock())


def fetch_json(
    url: str,
    *,
    user_agent: str,
    timeout: int,
    semaphore: object,
    rate_limit_fn: Callable[[], None],
    urlopen_fn: Callable[..., object],
    record_timeout: Optional[Callable[[], None]] = None,
    request_headers: Optional[Dict[str, str]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Optional[object]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    if isinstance(request_headers, dict):
        headers.update({str(k): str(v) for k, v in request_headers.items()})
    request = Request(url, headers=headers)
    return _execute_json_request(
        request,
        timeout=timeout,
        semaphore=semaphore,
        rate_limit_fn=rate_limit_fn,
        urlopen_fn=urlopen_fn,
        record_timeout=record_timeout,
        sleep_fn=sleep_fn,
    )


def post_json(
    url: str,
    payload: object,
    *,
    user_agent: str,
    timeout: int,
    semaphore: object,
    rate_limit_fn: Callable[[], None],
    urlopen_fn: Callable[..., object],
    record_timeout: Optional[Callable[[], None]] = None,
    headers: Optional[Dict[str, str]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Optional[object]:
    request_headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if isinstance(headers, dict):
        request_headers.update({str(k): str(v) for k, v in headers.items()})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=request_headers, method="POST")
    return _execute_json_request(
        request,
        timeout=timeout,
        semaphore=semaphore,
        rate_limit_fn=rate_limit_fn,
        urlopen_fn=urlopen_fn,
        record_timeout=record_timeout,
        sleep_fn=sleep_fn,
    )


def _execute_json_request(
    request: Request,
    *,
    timeout: int,
    semaphore: object,
    rate_limit_fn: Callable[[], None],
    urlopen_fn: Callable[..., object],
    record_timeout: Optional[Callable[[], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Optional[object]:
    resolved_timeout = max(1, int(timeout))
    for attempt in range(3):
        try:
            with semaphore:
                rate_limit_fn()
                with urlopen_fn(request, timeout=resolved_timeout) as response:
                    return json.loads(response.read().decode("utf-8", errors="ignore"))
        except HTTPError as exc:
            code = getattr(exc, "code", None)
            if code in {429, 503} and attempt < 2:
                sleep_fn(0.8 * (attempt + 1))
                continue
            return None
        except (URLError, TimeoutError) as exc:
            message = str(exc or "").lower()
            if ("timed out" in message or "timeout" in message) and record_timeout:
                record_timeout()
            if attempt < 2:
                sleep_fn(0.5 * (attempt + 1))
                continue
            return None
        except Exception:
            return None
    return None
