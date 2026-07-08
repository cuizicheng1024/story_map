"""健康检查与就绪探测模块。

汇总 LLM、地理编码、静态产物、任务队列等关键依赖的就绪状态，
供 FastAPI 路由与 Prometheus 指标消费。
"""
from __future__ import annotations

from typing import Dict, Protocol, runtime_checkable

from ..core.observability import structured_log


@runtime_checkable
class HealthTaskService(Protocol):
    """Protocol for task services that support housekeeping and metrics snapshots."""

    def housekeep_runtime(self) -> Dict[str, object]: ...
    def runtime_metrics_snapshot(self) -> Dict[str, object]: ...


@runtime_checkable
class HealthLLMClient(Protocol):
    """Protocol for LLM clients that support health snapshots."""

    def health_snapshot(self) -> Dict[str, object]: ...


@runtime_checkable
class HealthProxyService(Protocol):
    """Protocol for proxy services that expose metrics and LLM client access."""

    def _get_llm_client(self) -> object: ...
    def metrics_snapshot(self) -> Dict[str, object]: ...


@runtime_checkable
class HealthStaticService(Protocol):
    """Protocol for static services that expose debug payload."""

    def debug_static_payload(self) -> Dict[str, object]: ...


def service_supports(obj: object, protocol: type) -> bool:
    """Safely check if a service object conforms to a given Protocol."""
    return isinstance(obj, protocol)


def runtime_health_snapshot(proxy_service: object, task_service: object | None = None) -> dict:
    llm_snapshot: dict = {}
    llm_error = ""
    client = None
    housekeep_payload: dict = {}
    try:
        if service_supports(task_service, HealthTaskService):
            housekeep_payload = dict(task_service.housekeep_runtime() or {})
    except Exception as exc:
        housekeep_payload = {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}
    try:
        if service_supports(proxy_service, HealthProxyService):
            client = proxy_service._get_llm_client()
        if service_supports(client, HealthLLMClient):
            llm_snapshot = dict(client.health_snapshot() or {})
    except Exception as exc:
        llm_error = str(exc).strip() or exc.__class__.__name__
        llm_snapshot = {}
    geocode_snapshot: dict = {}
    geocode_error = ""
    try:
        from ..map import map_client as map_client_utils
        geocode_snapshot = dict(getattr(map_client_utils, "geocode_metrics_snapshot")() or {})
    except Exception as exc:
        geocode_error = str(exc).strip() or exc.__class__.__name__
        geocode_snapshot = {}
    task_snapshot: dict = {}
    try:
        if service_supports(task_service, HealthTaskService):
            task_snapshot = dict(task_service.runtime_metrics_snapshot() or {})
    except Exception as exc:
        task_snapshot = {"ok": False, "alerts": [{"code": "task_metrics_failed", "level": "error", "detail": str(exc).strip() or exc.__class__.__name__}]}
    return {
        "ok": True,
        "llm": {
            "ok": not bool(llm_error),
            "health": llm_snapshot,
            "error": llm_error,
        },
        "geocode": {
            "ok": not bool(geocode_error),
            "metrics": geocode_snapshot,
            "error": geocode_error,
        },
        "task": task_snapshot,
        "housekeep": housekeep_payload,
        "proxy": proxy_service.metrics_snapshot()
        if service_supports(proxy_service, HealthProxyService)
        else {},
    }


def static_readiness_snapshot(static_service: object) -> dict:
    payload = {}
    try:
        if service_supports(static_service, HealthStaticService):
            payload = dict(static_service.debug_static_payload() or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}
    return {
        "ok": bool(payload.get("static_exists")) and bool(payload.get("index_exists")),
        "static_exists": bool(payload.get("static_exists")),
        "index_exists": bool(payload.get("index_exists")),
        "static_dir": str(payload.get("static_dir") or ""),
    }


def dependency_component_state(name: str, snapshot: dict, *, metrics: dict, error: str) -> dict:
    requests = int(metrics.get("requests", metrics.get("lookups", 0)) or 0)
    timeouts = int(metrics.get("timeouts", 0) or 0)
    success_rate = metrics.get("success_rate")
    timeout_rate = metrics.get("timeout_rate")
    alerts = []
    ok = not bool(error) and bool(snapshot)
    if bool(error):
        alerts.append({"code": f"{name}_unavailable", "level": "error", "detail": str(error)})
    if requests >= 3 and isinstance(success_rate, (int, float)) and float(success_rate) <= 0:
        ok = False
        alerts.append({"code": f"{name}_success_rate_zero", "level": "error", "detail": f"{name} 最近 {requests} 次请求成功率为 0。"})
    if requests >= 3 and isinstance(timeout_rate, (int, float)) and float(timeout_rate) >= 0.9:
        ok = False
        alerts.append({"code": f"{name}_timeout_rate_high", "level": "error", "detail": f"{name} 超时率过高：{timeout_rate}。"})
    return {
        "ok": bool(ok),
        "requests": requests,
        "timeouts": timeouts,
        "success_rate": success_rate,
        "timeout_rate": timeout_rate,
        "alerts": alerts,
    }


def build_readiness_payload(*, static_service: object, proxy_service: object, task_service: object) -> dict:
    runtime = runtime_health_snapshot(proxy_service, task_service=task_service)
    static = static_readiness_snapshot(static_service)
    alerts = [dict(item) for item in list((runtime.get("task") or {}).get("alerts") or []) if isinstance(item, dict)]
    llm_health = dict((runtime.get("llm") or {}).get("health") or {})
    llm_metrics = dict(llm_health.get("metrics") or {})
    llm_state = dependency_component_state(
        "llm",
        llm_health,
        metrics=llm_metrics,
        error=str((runtime.get("llm") or {}).get("error") or "").strip(),
    )
    geocode_metrics = dict((runtime.get("geocode") or {}).get("metrics") or {})
    geocode_state = dependency_component_state(
        "geocode",
        geocode_metrics,
        metrics=geocode_metrics,
        error=str((runtime.get("geocode") or {}).get("error") or "").strip(),
    )
    if not static.get("ok"):
        alerts.append({"code": "static_artifacts_missing", "level": "error", "detail": "静态首页产物不可用或 index.html 缺失。"})
    alerts.extend(list(llm_state.get("alerts") or []))
    alerts.extend(list(geocode_state.get("alerts") or []))
    serve_ready = bool(static.get("ok")) and bool((runtime.get("task") or {}).get("ok", True))
    generate_ready = serve_ready and bool(llm_state.get("ok")) and bool(geocode_state.get("ok"))
    return {
        "ok": bool(generate_ready),
        "service": "story_map",
        "version": "1",
        "serve_ready": bool(serve_ready),
        "generate_ready": bool(generate_ready),
        "static": static,
        "task": runtime.get("task") or {},
        "llm": runtime.get("llm") or {},
        "geocode": runtime.get("geocode") or {},
        "proxy": runtime.get("proxy") or {},
        "dependency_status": {
            "llm": llm_state,
            "geocode": geocode_state,
        },
        "alerts": alerts,
        "alert_rules": [
            {"code": "static_artifacts_missing", "level": "error", "threshold": "index.html 缺失或静态目录不可用"},
            {"code": "queue_backlog_high", "level": "error", "threshold": "pending > readiness_max_pending"},
            {"code": "running_task_stale", "level": "error", "threshold": "oldest_running_age_seconds > readiness_max_running_age_seconds"},
            {"code": "llm_unavailable", "level": "error", "threshold": "LLM client 初始化失败或最近依赖健康为 unavailable"},
            {"code": "geocode_unavailable", "level": "error", "threshold": "地理编码依赖不可用"},
        ],
    }


__all__ = [
    "build_readiness_payload",
    "dependency_component_state",
    "HealthLLMClient",
    "HealthProxyService",
    "HealthStaticService",
    "HealthTaskService",
    "runtime_health_snapshot",
    "service_supports",
    "static_readiness_snapshot",
]
