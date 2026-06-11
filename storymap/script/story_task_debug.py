from __future__ import annotations

import html
import json
from typing import Dict, List

try:
    from .story_agent_runtime import build_runtime_pdca, build_runtime_quality_framework, build_runtime_reflection, extract_agent_runtime_metadata, normalize_runtime_snapshot
    from .story_task_schema import build_status_info, normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta
except ImportError:
    from story_agent_runtime import build_runtime_pdca, build_runtime_quality_framework, build_runtime_reflection, extract_agent_runtime_metadata, normalize_runtime_snapshot
    from story_task_schema import build_status_info, normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta


def _sanitize_tool_trace(item: object) -> Dict[str, object]:
    trace = dict(item or {}) if isinstance(item, dict) else {}
    sanitized: Dict[str, object] = {
        "tool_name": str(trace.get("tool_name") or ""),
        "agent_step": str(trace.get("agent_step") or "").strip(),
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
    input_summary = str(trace.get("input_summary") or trace.get("input_preview") or "").strip()
    if input_summary:
        sanitized["input_summary"] = input_summary
    output_summary = str(trace.get("output_summary") or trace.get("output_preview") or "").strip()
    if output_summary:
        sanitized["output_summary"] = output_summary
    return sanitized


def _build_safe_runtime(runtime: object) -> Dict[str, object]:
    normalized = normalize_agent_runtime_metadata(runtime)
    return {
        "has_runtime": bool(normalized.get("has_runtime")),
        "status": str(normalized.get("status") or ""),
        "status_info": dict(normalized.get("status_info") or {}),
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


def _build_safe_runtime_snapshot(runtime: object) -> Dict[str, object]:
    snapshot = normalize_runtime_snapshot(runtime)
    state = dict(snapshot.get("state") or {})
    return {
        "person": str(snapshot.get("person") or ""),
        "max_llm_calls": snapshot.get("max_llm_calls"),
        "langgraph_available": bool(snapshot.get("langgraph_available")),
        "tool_specs": [dict(item) for item in list(snapshot.get("tool_specs") or []) if isinstance(item, dict)],
        "fallback": str(snapshot.get("fallback") or ""),
        "error": str(snapshot.get("error") or ""),
        "used_legacy_fallback": bool(snapshot.get("used_legacy_fallback")),
        "legacy_markdown_ok": bool(snapshot.get("legacy_markdown_ok")),
        "state": {
            "llm_calls_used": int(state.get("llm_calls_used") or 0),
            "llm_calls_limit": int(state.get("llm_calls_limit") or 0),
            "revision_count": int(state.get("revision_count") or 0),
            "max_revisions": int(state.get("max_revisions") or 0),
            "needs_revision": bool(state.get("needs_revision")),
            "needs_redraft": bool(state.get("needs_redraft")),
            "degraded_reasons": [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()],
            "execution_trace": [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()],
            "tool_traces": [_sanitize_tool_trace(item) for item in list(state.get("tool_traces") or [])],
            "memory_hits": {str(key): int(value or 0) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()},
            "memory_misses": {
                str(key): int(value or 0) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()
            },
            "plan": [str(item) for item in list(state.get("plan") or []) if str(item).strip()],
            "search_result": dict(state.get("search_result") or {}) if isinstance(state.get("search_result"), dict) else {},
            "place_maps": [dict(item) for item in list(state.get("place_maps") or []) if isinstance(item, dict)],
            "draft_markdown": str(state.get("draft_markdown") or ""),
            "final_markdown": str(state.get("final_markdown") or ""),
            "validation": dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {},
            "critic_feedback": [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)],
        },
    }


def _build_safe_runtime_reflection(runtime: object) -> Dict[str, object]:
    reflection = build_runtime_reflection(runtime)
    return {
        "status": str(reflection.get("status") or ""),
        "strengths": [str(item) for item in list(reflection.get("strengths") or []) if str(item).strip()],
        "bottlenecks": [str(item) for item in list(reflection.get("bottlenecks") or []) if str(item).strip()],
        "suggested_actions": [str(item) for item in list(reflection.get("suggested_actions") or []) if str(item).strip()],
        "llm_budget": dict(reflection.get("llm_budget") or {}),
        "retry_summary": dict(reflection.get("retry_summary") or {}),
        "tool_summary": dict(reflection.get("tool_summary") or {}),
        "memory_summary": dict(reflection.get("memory_summary") or {}),
    }


def _build_safe_runtime_pdca(runtime: object) -> Dict[str, object]:
    pdca = build_runtime_pdca(runtime)
    return {
        "status": str(pdca.get("status") or ""),
        "person": str(pdca.get("person") or ""),
        "plan": dict(pdca.get("plan") or {}),
        "do": dict(pdca.get("do") or {}),
        "check": dict(pdca.get("check") or {}),
        "act": dict(pdca.get("act") or {}),
    }


def _build_safe_runtime_quality_framework(runtime: object) -> Dict[str, object]:
    framework = build_runtime_quality_framework(runtime)
    return {
        "status": str(framework.get("status") or ""),
        "person": str(framework.get("person") or ""),
        "human": dict(framework.get("human") or {}),
        "machine": dict(framework.get("machine") or {}),
        "material": dict(framework.get("material") or {}),
        "method": dict(framework.get("method") or {}),
        "environment": dict(framework.get("environment") or {}),
        "measurement": dict(framework.get("measurement") or {}),
    }


def _is_usable_result_item(item: Dict[str, object]) -> bool:
    if bool(item.get("ok")):
        return True
    return str(item.get("status") or "").strip() == "degraded"


def _build_person_status_info(
    item: Dict[str, object],
    runtime: Dict[str, object],
    runtime_reflection: Dict[str, object],
) -> Dict[str, object]:
    if not _is_usable_result_item(item):
        return build_status_info("failed", hint=str(item.get("error") or "").strip() or "该人物生成失败。")
    result_status = str(item.get("status") or "").strip()
    if result_status == "degraded":
        runtime_status = str(runtime.get("status") or "").strip()
        if runtime_status == "degraded":
            return dict(runtime.get("status_info") or {})
        return build_status_info("degraded", hint=str(item.get("error") or "").strip() or "该人物使用降级结果完成。")
    reflection_status = str(runtime_reflection.get("status") or "").strip()
    if reflection_status == "degraded":
        bottlenecks = [str(item) for item in list(runtime_reflection.get("bottlenecks") or []) if str(item).strip()]
        return build_status_info("degraded", hint=(bottlenecks[0] if bottlenecks else "该人物 runtime 已出现降级信号。"))
    if reflection_status == "watch":
        bottlenecks = [str(item) for item in list(runtime_reflection.get("bottlenecks") or []) if str(item).strip()]
        return build_status_info("watch", hint=(bottlenecks[0] if bottlenecks else "该人物 runtime 需要关注。"))
    if bool(runtime.get("has_runtime")):
        return dict(runtime.get("status_info") or {})
    return build_status_info("completed", hint="该人物生成成功，但未记录 runtime。")


def _build_ui_payload(task: Dict[str, object], result: Dict[str, object], meta: Dict[str, object]) -> Dict[str, object]:
    task_status_info = dict(task.get("status_info") or {})
    result_status_info = dict(result.get("status_info") or {})
    meta_status_info = dict(meta.get("status_info") or {})
    task_code = str(task_status_info.get("code") or "").strip()
    result_code = str(result_status_info.get("code") or "").strip()
    meta_code = str(meta_status_info.get("code") or "").strip()
    if result_code in {"failed", "partial_failed"}:
        banner = result_status_info
    elif task_code in {"failed", "partial_failed"}:
        banner = task_status_info
    elif meta_code in {"watch", "degraded", "failed"}:
        banner = meta_status_info
    else:
        banner = result_status_info or task_status_info or meta_status_info or build_status_info("empty")
    return {
        "task_status": task_status_info,
        "result_status": result_status_info,
        "runtime_status": meta_status_info,
        "banner": banner,
    }


def build_task_debug_payload(snapshot: object) -> Dict[str, object]:
    task = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    meta = normalize_aggregated_runtime_meta(result.get("meta") or {})
    task_view = {
        "id": str(task.get("id") or ""),
        "status": str(task.get("status") or ""),
        "status_info": dict(task.get("status_info") or {}),
        "text": str(task.get("text") or ""),
        "error": str(task.get("error") or ""),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }
    result_view = {
        "ok": _is_usable_result_item(result),
        "status": str(result.get("status") or ""),
        "status_info": dict(result.get("status_info") or {}),
        "people": [str(item) for item in list(result.get("people") or []) if str(item).strip()],
        "success_count": int(result.get("success_count") or 0),
        "failed_count": int(result.get("failed_count") or 0),
        "failed_people": [str(item) for item in list(result.get("failed_people") or []) if str(item).strip()],
    }
    people: List[Dict[str, object]] = []
    for item in list(result.get("results") or []):
        if not isinstance(item, dict):
            continue
        runtime_source = item.get("_agent_runtime")
        runtime_snapshot = _build_safe_runtime_snapshot(runtime_source)
        runtime = _build_safe_runtime(extract_agent_runtime_metadata(runtime_source))
        runtime_reflection = _build_safe_runtime_reflection(runtime_source)
        runtime_pdca = _build_safe_runtime_pdca(runtime_source)
        runtime_quality = _build_safe_runtime_quality_framework(runtime_source)
        status_info = _build_person_status_info(item, runtime, runtime_reflection)
        people.append(
            {
                "person": str(item.get("person") or runtime.get("person") or ""),
                "ok": _is_usable_result_item(item),
                "error": str(item.get("error") or ""),
                "status_info": status_info,
                "runtime": runtime,
                "runtime_snapshot": runtime_snapshot,
                "runtime_reflection": runtime_reflection,
                "runtime_pdca": runtime_pdca,
                "runtime_quality": runtime_quality,
                "memory_hits": dict(runtime.get("memory_hits") or {}),
                "memory_misses": dict(runtime.get("memory_misses") or {}),
            }
        )
    return {
        "task": task_view,
        "result": result_view,
        "meta": meta,
        "ui": _build_ui_payload(task_view, result_view, meta),
        "people": people,
    }


def _render_kv_rows(data: Dict[str, object]) -> str:
    rows = []
    for key, value in data.items():
        pretty = html.escape(json.dumps(value, ensure_ascii=False)) if isinstance(value, (dict, list)) else html.escape(str(value))
        rows.append(f"<tr><th>{html.escape(str(key))}</th><td><code>{pretty}</code></td></tr>")
    return "".join(rows)


def _render_status_banner(info: Dict[str, object]) -> str:
    level = str(info.get("level") or "muted").strip()
    label = html.escape(str(info.get("label") or str(info.get("code") or "状态未知")))
    hint = html.escape(str(info.get("hint") or "").strip())
    hint_html = f'<div class="banner-hint">{hint}</div>' if hint else ""
    return (
        f'<div class="banner banner-{html.escape(level)}">'
        f"<strong>{label}</strong>"
        f"{hint_html}"
        "</div>"
    )


def render_task_debug_html(snapshot: object, *, storage: object = None) -> str:
    payload = build_task_debug_payload(snapshot)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    ui = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
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
            f"{_render_status_banner(dict(item.get('status_info') or {}))}"
            "<h3>Memory Telemetry</h3>"
            f"<pre>{html.escape(json.dumps({'hits': item.get('memory_hits') or {}, 'misses': item.get('memory_misses') or {}}, ensure_ascii=False, indent=2))}</pre>"
            "<h3>Runtime Snapshot</h3>"
            f"<pre>{html.escape(json.dumps(item.get('runtime_snapshot') or {}, ensure_ascii=False, indent=2))}</pre>"
            "<h3>Runtime Reflection</h3>"
            f"<pre>{html.escape(json.dumps(item.get('runtime_reflection') or {}, ensure_ascii=False, indent=2))}</pre>"
            "<h3>PDCA View</h3>"
            f"<pre>{html.escape(json.dumps(item.get('runtime_pdca') or {}, ensure_ascii=False, indent=2))}</pre>"
            "<h3>6M View</h3>"
            f"<pre>{html.escape(json.dumps(item.get('runtime_quality') or {}, ensure_ascii=False, indent=2))}</pre>"
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
    .banner {{ border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; border: 1px solid transparent; }}
    .banner-success {{ background: #ecfdf5; color: #166534; border-color: #a7f3d0; }}
    .banner-warning {{ background: #fffbeb; color: #92400e; border-color: #fde68a; }}
    .banner-error {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
    .banner-info {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
    .banner-muted {{ background: #f9fafb; color: #4b5563; border-color: #e5e7eb; }}
    .banner-hint {{ margin-top: 6px; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 10px; border-top: 1px solid #f0f0f0; vertical-align: top; }}
    th {{ width: 220px; color: #374151; }}
    pre {{ background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow: auto; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <h1>Task Debug</h1>
  {_render_status_banner(dict(ui.get("banner") or {}))}
  <section>
    <h2>Task</h2>
    <table>{_render_kv_rows(task)}</table>
  </section>
  <section>
    <h2>Task Result</h2>
    <table>{_render_kv_rows(result)}</table>
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
