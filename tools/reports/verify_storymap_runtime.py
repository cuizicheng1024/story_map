from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _safe_join(root: str, path: str) -> str:
    base = str(root or "").rstrip("/")
    raw = str(path or "")
    raw = raw if raw.startswith("/") else ("/" + raw if raw else "/")
    segments = [quote(seg) for seg in raw.split("/") if seg]
    return base + "/" + "/".join(segments)


def _request_json(url: str, *, method: str = "GET", body: Optional[Dict[str, object]] = None, timeout: float = 20.0) -> Dict[str, Any]:
    payload = None
    headers = {"User-Agent": "storymap-runtime-verify", "Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(url: str, *, timeout: float = 20.0) -> str:
    request = Request(url, headers={"User-Agent": "storymap-runtime-verify", "Accept": "text/html,application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def verify_runtime(
    *,
    base_url: str,
    person: str = "李白",
    timeout: float = 20.0,
    poll_timeout: float = 45.0,
    request_json=_request_json,
    request_text=_request_text,
    sleep=time.sleep,
    now=time.time,
) -> Dict[str, Any]:
    root = str(base_url or "").rstrip("/")
    checks = []

    def _record(name: str, ok: bool, **extra: object) -> None:
        checks.append({"name": name, "ok": bool(ok), **extra})

    health = request_json(_safe_join(root, "/health"), timeout=timeout)
    _record("health", bool(health.get("ok")), actual=health)

    ready = request_json(_safe_join(root, "/health/ready"), timeout=timeout)
    _record("readiness", bool(ready.get("ok")), actual=ready)

    metrics_text = request_text(_safe_join(root, "/metrics"), timeout=timeout)
    _record("metrics", "storymap_generate_readiness" in metrics_text and "storymap_readiness" in metrics_text, length=len(metrics_text))

    index_html = request_text(_safe_join(root, "/"), timeout=timeout)
    _record("homepage", "人类群星闪耀时" in index_html and "pixelGenCompactText" in index_html, length=len(index_html))

    profile_html = request_text(_safe_join(root, "/李白.html"), timeout=timeout)
    _record("profile_page", "window.__BUILD_META__" in profile_html and "李白" in profile_html, length=len(profile_html))

    generated = request_json(_safe_join(root, "/generate"), method="POST", body={"person": person}, timeout=timeout)
    task_id = str(generated.get("task_id") or "").strip()
    _record("generate_submit", bool(generated.get("ok")) and bool(task_id), actual=generated)

    final_snapshot: Dict[str, Any] = {}
    if task_id:
        deadline = now() + float(poll_timeout)
        while now() < deadline:
            final_snapshot = request_json(_safe_join(root, "/task") + f"?id={quote(task_id)}", timeout=timeout)
            if str(final_snapshot.get("status") or "").strip() in {"completed", "partial_failed", "failed", "cancelled", "timed_out"}:
                break
            sleep(0.5)
        terminal_status = str(final_snapshot.get("status") or "").strip()
        _record(
            "generate_task_terminal",
            terminal_status in {"completed", "partial_failed"},
            status=terminal_status,
            actual=final_snapshot,
        )
    ok = all(bool(item.get("ok")) for item in checks)
    return {"ok": ok, "base_url": root, "checks": checks}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发布后自动验收 StoryMap 运行时服务")
    parser.add_argument("base_url", nargs="?", default="http://124.174.16.20", help="服务基地址")
    parser.add_argument("--person", default="李白", help="用于生成链路验收的人物")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次请求超时时间（秒）")
    parser.add_argument("--poll-timeout", type=float, default=45.0, help="轮询任务的最长等待时间（秒）")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        report = verify_runtime(
            base_url=str(args.base_url),
            person=str(args.person),
            timeout=float(args.timeout),
            poll_timeout=float(args.poll_timeout),
        )
    except HTTPError as exc:
        report = {"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
