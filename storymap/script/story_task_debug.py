from __future__ import annotations

import html
import json
from typing import Dict, List

try:
    from .story_agent_runtime import extract_agent_runtime_metadata
    from .story_task_schema import normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta
except ImportError:
    from story_agent_runtime import extract_agent_runtime_metadata
    from story_task_schema import normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta


def _sanitize_tool_trace(item: object) -> Dict[str, object]:
    trace = dict(item or {}) if isinstance(item, dict) else {}
    sanitized: Dict[str, object] = {
        "tool_name": str(trace.get("tool_name") or ""),
        "success": bool(trace.get("success")),
        "attempt": int(trace.get("attempt") or 0),
        "duration_ms": int(trace.get("duration_ms") or 0),
        "timed_out": bool(trace.get("timed_out")),
        "permission": str(trace.get("permission") or ""),
        "cost_tier": str(trace.get("cost_tier") or ""),
    }
    memory_bucket = str(trace.get("memory_bucket") or "").strip()
    if memory_bucket:
        sanitized["memory_bucket"] = memory_bucket
        sanitized["memory_hit"] = bool(trace.get("memory_hit"))
    error = str(trace.get("error") or "").strip()
    if error:
        sanitized["error"] = error
    return sanitized


def _build_safe_runtime(runtime: object) -> Dict[str, object]:
    normalized = normalize_agent_runtime_metadata(runtime)
    return {
        "person": str(normalized.get("person") or ""),
        "langgraph_available": bool(normalized.get("langgraph_available")),
        "used_legacy_fallback": bool(normalized.get("used_legacy_fallback")),
        "legacy_markdown_ok": bool(normalized.get("legacy_markdown_ok")),
        "fallback": str(normalized.get("fallback") or ""),
        "error": str(normalized.get("error") or ""),
        "max_llm_calls": normalized.get("max_llm_calls"),
        "llm_calls_used": normalized.get("llm_calls_used"),
        "llm_calls_limit": normalized.get("llm_calls_limit"),
        "degraded_reasons": list(normalized.get("degraded_reasons") or []),
        "execution_trace": list(normalized.get("execution_trace") or []),
        "tool_traces": [_sanitize_tool_trace(item) for item in list(normalized.get("tool_traces") or [])],
        "memory_hits": dict(normalized.get("memory_hits") or {}),
        "memory_misses": dict(normalized.get("memory_misses") or {}),
    }


def build_task_debug_payload(snapshot: object) -> Dict[str, object]:
    task = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    meta = normalize_aggregated_runtime_meta(result.get("meta") or {})
    people: List[Dict[str, object]] = []
    for item in list(result.get("results") or []):
        if not isinstance(item, dict):
            continue
        runtime = _build_safe_runtime(extract_agent_runtime_metadata(item.get("_agent_runtime")))
        people.append(
            {
                "person": str(item.get("person") or runtime.get("person") or ""),
                "ok": bool(item.get("ok")),
                "error": str(item.get("error") or ""),
                "runtime": runtime,
                "memory_hits": dict(runtime.get("memory_hits") or {}),
                "memory_misses": dict(runtime.get("memory_misses") or {}),
            }
        )
    return {
        "task": {
            "id": str(task.get("id") or ""),
            "status": str(task.get("status") or ""),
            "text": str(task.get("text") or ""),
            "error": str(task.get("error") or ""),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        },
        "meta": meta,
        "people": people,
    }


def _render_kv_rows(data: Dict[str, object]) -> str:
    rows = []
    for key, value in data.items():
        pretty = html.escape(json.dumps(value, ensure_ascii=False)) if isinstance(value, (dict, list)) else html.escape(str(value))
        rows.append(f"<tr><th>{html.escape(str(key))}</th><td><code>{pretty}</code></td></tr>")
    return "".join(rows)


def render_task_debug_html(snapshot: object, *, storage: object = None) -> str:
    payload = build_task_debug_payload(snapshot)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    people = list(payload.get("people") or [])
    storage_section = ""
    if isinstance(storage, dict) and storage:
        storage_section = (
            "<section><h2>task.sqlite3</h2><table>"
            f"{_render_kv_rows(storage)}"
            "</table></section>"
        )
    people_html = []
    for item in people:
        if not isinstance(item, dict):
            continue
        runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
        people_html.append(
            "<section>"
            f"<h2>{html.escape(str(item.get('person') or '未知人物'))}</h2>"
            "<h3>Memory Telemetry</h3>"
            f"<pre>{html.escape(json.dumps({'hits': item.get('memory_hits') or {}, 'misses': item.get('memory_misses') or {}}, ensure_ascii=False, indent=2))}</pre>"
            "<h3>Runtime Meta</h3>"
            f"<pre>{html.escape(json.dumps(runtime, ensure_ascii=False, indent=2))}</pre>"
            "</section>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Task Debug</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; line-height: 1.5; background: #fafafa; color: #111; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 10px; border-top: 1px solid #f0f0f0; vertical-align: top; }}
    th {{ width: 220px; color: #374151; }}
    pre {{ background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow: auto; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <h1>Task Debug</h1>
  <section>
    <h2>Task</h2>
    <table>{_render_kv_rows(task)}</table>
  </section>
  <section>
    <h2>Runtime Summary</h2>
    <table>{_render_kv_rows(meta)}</table>
  </section>
  {storage_section}
  {''.join(people_html)}
</body>
</html>"""


__all__ = [
    "build_task_debug_payload",
    "render_task_debug_html",
]
