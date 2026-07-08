"""Prometheus 指标导出模块。

将健康检查就绪状态、任务队列、依赖组件状态等转换为 Prometheus 文本格式。
"""
from __future__ import annotations

from ..core.observability import prometheus_lines
from .health import build_readiness_payload


def build_metrics_payload(*, static_service: object, proxy_service: object, task_service: object) -> str:
    readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
    task = dict(readiness.get("task") or {})
    task_queue = dict(task.get("queue") or {})
    task_counters = dict(task.get("counters") or {})
    dependency_status = dict(readiness.get("dependency_status") or {})
    proxy_metrics = dict(readiness.get("proxy") or {})
    lines = []
    lines += prometheus_lines("storymap_readiness", readiness.get("ok"), help_text="StoryMap overall readiness")
    lines += prometheus_lines("storymap_serve_readiness", readiness.get("serve_ready"), help_text="StoryMap serve readiness")
    lines += prometheus_lines("storymap_generate_readiness", readiness.get("generate_ready"), help_text="StoryMap generate readiness")
    lines += prometheus_lines("storymap_static_ready", (readiness.get("static") or {}).get("ok"), help_text="Static artifact readiness")
    for key, value in task_queue.items():
        lines += prometheus_lines(f"storymap_task_queue_{key}", value)
    for key, value in task_counters.items():
        metric_type = "counter" if key.endswith("_total") or key in {
            "submitted",
            "deduped",
            "retried",
            "interrupted",
            "auto_retried",
            "cancel_requested",
            "cancelled",
            "timed_out",
            "completed",
            "failed",
            "partial_failed",
            "crashed",
        } else "gauge"
        lines += prometheus_lines(f"storymap_task_{key}", value, metric_type=metric_type)
    for component, payload in dependency_status.items():
        payload_dict = dict(payload or {})
        lines += prometheus_lines("storymap_dependency_ready", payload_dict.get("ok"), labels={"component": component})
        for key in ("requests", "timeouts", "success_rate", "timeout_rate"):
            if key in payload_dict:
                lines += prometheus_lines(f"storymap_dependency_{key}", payload_dict.get(key), labels={"component": component})
    for key, value in proxy_metrics.items():
        metric_type = "counter" if key.startswith("proxy_") and key not in {"breaker_open"} else "gauge"
        lines += prometheus_lines(f"storymap_proxy_{key}", value, metric_type=metric_type)
    active_alert_codes = {str(item.get("code") or "") for item in list(readiness.get("alerts") or []) if isinstance(item, dict)}
    for rule in list(readiness.get("alert_rules") or []):
        if not isinstance(rule, dict):
            continue
        code = str(rule.get("code") or "").strip()
        if not code:
            continue
        lines += prometheus_lines(
            "storymap_alert_rule_info",
            1,
            labels={
                "code": code,
                "level": str(rule.get("level") or "info"),
                "threshold": str(rule.get("threshold") or ""),
            },
        )
        lines += prometheus_lines(
            "storymap_alert_active",
            code in active_alert_codes,
            labels={"code": code, "level": str(rule.get("level") or "info")},
        )
    return "\n".join(lines) + "\n"


__all__ = ["build_metrics_payload"]
