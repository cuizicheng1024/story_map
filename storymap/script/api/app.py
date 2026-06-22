import json
import os
import secrets
import time
import threading
import uvicorn
from datetime import date
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pathlib import Path

from ..core.observability import prometheus_lines, structured_log
from ..runtime.task_debug import render_task_debug_html


def _enforce_origin(request: FastAPIRequest, resolve_cors_origin) -> None:
    origin = str(request.headers.get("origin", "") or "").strip()
    if origin.lower() == "null":
        origin = ""
    if origin and not resolve_cors_origin(origin):
        raise HTTPException(status_code=403, detail="origin not allowed")


_RUNTIME_DEBUG_TOKEN_ENV_KEYS = ("STORYMAP_RUNTIME_DEBUG_TOKEN", "MAP_STORY_RUNTIME_DEBUG_TOKEN")
_RUNTIME_DEBUG_TOKEN_HEADER_KEYS = ("x-storymap-debug-token", "x-runtime-debug-token")


def _runtime_health_snapshot(proxy_service: object, task_service: object | None = None) -> dict:
    llm_snapshot: dict = {}
    llm_error = ""
    client = None
    housekeep_payload: dict = {}
    try:
        if task_service is not None and hasattr(task_service, "housekeep_runtime") and callable(getattr(task_service, "housekeep_runtime")):
            housekeep_payload = dict(getattr(task_service, "housekeep_runtime")() or {})
    except Exception as exc:
        housekeep_payload = {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}
    try:
        getter = getattr(proxy_service, "_get_llm_client", None)
        if callable(getter):
            client = getter()
        if client is not None and hasattr(client, "health_snapshot") and callable(getattr(client, "health_snapshot")):
            llm_snapshot = dict(getattr(client, "health_snapshot")() or {})
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
        if task_service is not None and hasattr(task_service, "runtime_metrics_snapshot") and callable(getattr(task_service, "runtime_metrics_snapshot")):
            task_snapshot = dict(getattr(task_service, "runtime_metrics_snapshot")() or {})
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
        "proxy": dict(getattr(proxy_service, "metrics_snapshot")() or {})
        if hasattr(proxy_service, "metrics_snapshot") and callable(getattr(proxy_service, "metrics_snapshot"))
        else {},
    }


def _static_readiness_snapshot(static_service: object) -> dict:
    payload = {}
    try:
        if hasattr(static_service, "debug_static_payload") and callable(getattr(static_service, "debug_static_payload")):
            payload = dict(getattr(static_service, "debug_static_payload")() or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}
    return {
        "ok": bool(payload.get("static_exists")) and bool(payload.get("index_exists")),
        "static_exists": bool(payload.get("static_exists")),
        "index_exists": bool(payload.get("index_exists")),
        "static_dir": str(payload.get("static_dir") or ""),
    }


def _dependency_component_state(name: str, snapshot: dict, *, metrics: dict, error: str) -> dict:
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


def _build_readiness_payload(*, static_service: object, proxy_service: object, task_service: object) -> dict:
    runtime = _runtime_health_snapshot(proxy_service, task_service=task_service)
    static = _static_readiness_snapshot(static_service)
    alerts = [dict(item) for item in list((runtime.get("task") or {}).get("alerts") or []) if isinstance(item, dict)]
    llm_health = dict((runtime.get("llm") or {}).get("health") or {})
    llm_metrics = dict(llm_health.get("metrics") or {})
    llm_state = _dependency_component_state(
        "llm",
        llm_health,
        metrics=llm_metrics,
        error=str((runtime.get("llm") or {}).get("error") or "").strip(),
    )
    geocode_metrics = dict((runtime.get("geocode") or {}).get("metrics") or {})
    geocode_state = _dependency_component_state(
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


def _metrics_payload(*, static_service: object, proxy_service: object, task_service: object) -> str:
    readiness = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
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
        lines += prometheus_lines(f"storymap_dependency_ready", payload_dict.get("ok"), labels={"component": component})
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


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_GENERATE_DAILY_LIMIT_PATH = _REPO_ROOT / "artifacts" / "runtime" / "generate_daily_quota.json"
_DEFAULT_GENERATE_IDEMPOTENCY_PATH = _REPO_ROOT / "artifacts" / "runtime" / "generate_idempotency.json"
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


def _first_env(*keys: str) -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return ""


def _request_client_host(request: FastAPIRequest) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    client_host = str(getattr(getattr(request, "client", None), "host", "") or "").strip()
    return forwarded or real_ip or client_host or ""


def _runtime_debug_token() -> str:
    return _first_env(*_RUNTIME_DEBUG_TOKEN_ENV_KEYS)


def _has_runtime_debug_token(request: FastAPIRequest) -> bool:
    expected = _runtime_debug_token()
    if not expected:
        return False
    for header_name in _RUNTIME_DEBUG_TOKEN_HEADER_KEYS:
        value = str(request.headers.get(header_name) or "").strip()
        if value and secrets.compare_digest(value, expected):
            return True
    return False


def _enforce_runtime_debug_access(request: FastAPIRequest) -> None:
    if _has_runtime_debug_token(request):
        return
    raise HTTPException(status_code=403, detail="runtime debug access denied")


def _generate_daily_limit() -> int:
    raw = _first_env(*_GENERATE_DAILY_LIMIT_ENV_KEYS)
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _generate_daily_limit_path() -> Path:
    raw = _first_env(*_GENERATE_DAILY_LIMIT_PATH_ENV_KEYS)
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_GENERATE_DAILY_LIMIT_PATH


def _generate_idempotency_path() -> Path:
    raw = _first_env(*_GENERATE_IDEMPOTENCY_PATH_ENV_KEYS)
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_GENERATE_IDEMPOTENCY_PATH


def _generate_idempotency_ttl_seconds() -> int:
    raw = _first_env(*_GENERATE_IDEMPOTENCY_TTL_ENV_KEYS)
    if not raw:
        return 6 * 3600
    try:
        return max(60, int(raw))
    except ValueError:
        return 6 * 3600


def _request_client_bucket(request: FastAPIRequest) -> str:
    return _request_client_host(request) or "unknown"


def _request_idempotency_key(request: FastAPIRequest, body: object) -> str:
    for header_name in _GENERATE_IDEMPOTENCY_HEADER_KEYS:
        value = str(request.headers.get(header_name) or "").strip()
        if value:
            return value[:256]
    if isinstance(body, dict):
        value = str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip()
        if value:
            return value[:256]
    return ""


class _GenerateDailyQuotaStore:
    def __init__(self, target_path: Path) -> None:
        self._target_path = Path(target_path)
        self._lock = threading.Lock()

    def _load_locked(self) -> dict:
        if not self._target_path.exists():
            return {}
        try:
            payload = json.loads(self._target_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_locked(self, payload: dict) -> None:
        self._target_path.parent.mkdir(parents=True, exist_ok=True)
        # 用 pid 区分临时文件，避免多进程并发写入时彼此覆盖 .tmp
        # 而导致目标文件被部分写入或丢失。
        tmp_path = self._target_path.with_suffix(self._target_path.suffix + f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._target_path)

    def consume(self, bucket: str, limit: int) -> dict:
        if limit <= 0:
            return {"allowed": True, "limit": 0, "used": 0, "remaining": None, "reset_on": date.today().isoformat()}
        bucket_key = str(bucket or "").strip() or "unknown"
        today = date.today().isoformat()
        with self._lock:
            payload = self._load_locked()
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
            self._save_locked(payload)
            return {
                "allowed": True,
                "limit": limit,
                "used": used + 1,
                "remaining": max(0, limit - used - 1),
                "reset_on": today,
            }


_GENERATE_DAILY_QUOTA_STORES: dict[str, _GenerateDailyQuotaStore] = {}
_GENERATE_IDEMPOTENCY_STORES: dict[str, "_GenerateIdempotencyStore"] = {}
_STAR_OFFICE_NAME = "橙子科技公司"


def _generate_daily_quota_store() -> _GenerateDailyQuotaStore:
    path = str(_generate_daily_limit_path())
    store = _GENERATE_DAILY_QUOTA_STORES.get(path)
    if store is None:
        store = _GenerateDailyQuotaStore(Path(path))
        _GENERATE_DAILY_QUOTA_STORES[path] = store
    return store


def _list_task_items(task_service: object, *, status: str = "", limit: int = 1) -> list[dict]:
    if not hasattr(task_service, "list_tasks") or not callable(getattr(task_service, "list_tasks")):
        return []
    try:
        payload = dict(getattr(task_service, "list_tasks")(limit=limit, offset=0, status=status) or {})
    except Exception:
        return []
    return [dict(item) for item in list(payload.get("tasks") or []) if isinstance(item, dict)]


def _task_updated_at(task: dict) -> float:
    try:
        return float(task.get("updated_at") or task.get("created_at") or 0.0)
    except Exception:
        return 0.0


def _task_person_label(task: dict, *, default: str = "历史人物") -> str:
    people = [str(item).strip() for item in list(task.get("people") or []) if str(item).strip()]
    text = str(task.get("text") or "").strip()
    return people[0] if people else (text or default)


def _list_recent_task_items(task_service: object, *, limit: int = 8) -> list[dict]:
    return _list_task_items(task_service, status="", limit=limit)


def _pick_task_by_statuses(items: list[dict], *statuses: str) -> dict:
    normalized = {str(item).strip() for item in statuses if str(item).strip()}
    if not normalized:
        return {}
    for item in items:
        if str(item.get("status") or "").strip() in normalized:
            return dict(item)
    return {}


def _is_recent_task(task: dict, *, window_seconds: int = 900) -> bool:
    updated_at = _task_updated_at(task)
    return updated_at > 0 and (time.time() - updated_at) <= max(int(window_seconds), 60)


def _star_office_task_context(task_service: object) -> dict:
    recent = _list_recent_task_items(task_service, limit=8)
    active = _pick_task_by_statuses(recent, "running", "queued")
    latest_success = _pick_task_by_statuses(recent, "completed")
    latest_failure = _pick_task_by_statuses(recent, "failed", "partial_failed", "timed_out", "cancelled", "interrupted")
    latest_any = dict(recent[0]) if recent else {}
    return {
        "recent": recent,
        "active": active,
        "latest_success": latest_success,
        "latest_failure": latest_failure,
        "latest_any": latest_any,
    }


def _pick_latest_task(*tasks: dict) -> dict:
    picked: dict = {}
    picked_updated_at = -1.0
    for task in tasks:
        current = dict(task or {})
        if not current:
            continue
        updated_at = _task_updated_at(current)
        if updated_at >= picked_updated_at:
            picked = current
            picked_updated_at = updated_at
    return picked


def _star_office_status_payload(*, task_service: object, readiness: dict) -> dict:
    context = _star_office_task_context(task_service)
    task = dict(context.get("active") or {})
    status = str(task.get("status") or "").strip()
    label = _task_person_label(task)
    if not readiness.get("serve_ready"):
        return {
            "state": "idle",
            "detail": "服务恢复中，正在等待站点与运行态恢复。",
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if not readiness.get("generate_ready"):
        return {
            "state": "idle",
            "detail": "实时生成人物已暂停，正在等待依赖恢复。",
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    if status == "running":
        return {
            "state": "executing",
            "detail": f"正在处理 {label} 的故事地图生成",
            "progress": 62,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if status == "queued":
        return {
            "state": "researching",
            "detail": f"{label} 正在排队，等待 Agent 开始执行",
            "progress": 18,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if latest_terminal and str(latest_terminal.get("status") or "").strip() == "completed":
        success_label = _task_person_label(latest_terminal)
        success_state = "syncing" if _is_recent_task(latest_terminal, window_seconds=900) else "idle"
        return {
            "state": success_state,
            "detail": f"最近已完成 {success_label} 的生成，系统当前待命，可继续处理新人物。",
            "progress": 100 if success_state == "syncing" else 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if latest_terminal:
        failed_label = _task_person_label(latest_terminal)
        detail = str(latest_terminal.get("error") or "").strip()
        summary = f"最近一次 {failed_label} 任务未完全成功，系统已恢复待命，可直接重试或继续新任务。"
        if detail:
            summary = f"{summary} 上次异常：{detail}"
        return {
            "state": "idle",
            "detail": summary,
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    return {
        "state": "idle",
        "detail": "待命中，随时可以继续处理新的历史人物任务。",
        "progress": 0,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "officeName": _STAR_OFFICE_NAME,
    }


def _build_star_office_agent(*, agent_id: str, name: str, state: str, auth_status: str, area: str, avatar: str) -> dict:
    return {
        "agentId": str(agent_id).strip(),
        "name": str(name).strip(),
        "state": str(state).strip() or "idle",
        "authStatus": str(auth_status).strip() or "approved",
        "area": str(area).strip() or "breakroom",
        "avatar": str(avatar).strip() or "guest_role_1",
    }


def _star_office_agents_payload(*, task_service: object, readiness: dict) -> list[dict]:
    context = _star_office_task_context(task_service)
    active = dict(context.get("active") or {})
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    agents: list[dict] = []

    def add_agent(agent_id: str, name: str, state: str, *, auth_status: str = "approved", area: str = "", avatar: str = "") -> None:
        normalized_id = str(agent_id).strip()
        if not normalized_id or any(str(item.get("agentId") or "").strip() == normalized_id for item in agents):
            return
        agents.append(
            _build_star_office_agent(
                agent_id=normalized_id,
                name=name,
                state=state,
                auth_status=auth_status,
                area=area,
                avatar=avatar,
            )
        )

    if not readiness.get("serve_ready"):
        add_agent("site-guard", "站点守护 Agent", "idle", area="breakroom", avatar="guest_role_5")
        add_agent("recover-agent", "恢复巡检 Agent", "researching", area="writing", avatar="guest_role_4")
        return agents

    active_status = str(active.get("status") or "").strip()
    if active_status == "running":
        add_agent("orange-agent", "橙子 Agent", "executing", area="writing", avatar="guest_role_1")
        add_agent("dispatch-agent", "排队调度 Agent", "researching", area="researching", avatar="guest_role_3")
        return agents
    if active_status == "queued":
        add_agent("dispatch-agent", "排队调度 Agent", "researching", area="researching", avatar="guest_role_3")
        add_agent("orange-agent", "橙子 Agent", "idle", area="breakroom", avatar="guest_role_1")
        return agents

    if (
        latest_terminal
        and str(latest_terminal.get("status") or "").strip() == "completed"
        and _is_recent_task(latest_terminal, window_seconds=900)
    ):
        add_agent("sync-agent", "发布同步 Agent", "syncing", area="writing", avatar="guest_role_2")
    elif latest_terminal and _is_recent_task(latest_terminal, window_seconds=900):
        add_agent("recover-agent", "恢复巡检 Agent", "error", area="error", avatar="guest_role_4")

    if readiness.get("generate_ready"):
        add_agent("reception-agent", "前台接待 Agent", "idle", area="breakroom", avatar="guest_role_6")
        add_agent("archive-agent", "档案整理 Agent", "idle", area="breakroom", avatar="guest_role_5")
    else:
        add_agent("dependency-agent", "依赖巡检 Agent", "researching", area="writing", avatar="guest_role_4")
        add_agent("reception-agent", "前台接待 Agent", "idle", area="breakroom", avatar="guest_role_6")
    return agents[:3]


def _star_office_memo_payload(*, task_service: object, readiness: dict) -> dict:
    context = _star_office_task_context(task_service)
    active = dict(context.get("active") or {})
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    active_status = str(active.get("status") or "").strip()
    if active_status == "running":
        memo = f"当前任务：{_task_person_label(active)}，正在生成故事地图与人物页。"
    elif active_status == "queued":
        memo = f"当前任务：{_task_person_label(active)}，正在排队等待 Agent 开始执行。"
    elif latest_terminal and str(latest_terminal.get("status") or "").strip() == "completed":
        memo = f"最近完成：{_task_person_label(latest_terminal)}，人物页与首页数据已同步。"
    elif latest_terminal:
        memo = f"最近一次任务未完全成功：{_task_person_label(latest_terminal)}，系统已恢复待命，可直接重试。"
    else:
        memo = "当前办公室待命中，暂无新的生成任务，静态人物页仍可正常浏览。"
    if not readiness.get("generate_ready"):
        memo += " 目前实时生成暂停，系统正在等待依赖恢复。"
    return {"success": True, "date": str(date.today()), "memo": memo}


class _GenerateIdempotencyStore:
    def __init__(self, target_path: Path, *, ttl_seconds: int) -> None:
        self._target_path = Path(target_path)
        self._ttl_seconds = max(int(ttl_seconds), 60)
        self._lock = threading.Lock()

    def _load_locked(self) -> dict:
        if not self._target_path.exists():
            return {"entries": {}}
        try:
            payload = json.loads(self._target_path.read_text(encoding="utf-8"))
        except Exception:
            return {"entries": {}}
        return payload if isinstance(payload, dict) else {"entries": {}}

    def _save_locked(self, payload: dict) -> None:
        self._target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._target_path.with_suffix(self._target_path.suffix + f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._target_path)

    def _prune_locked(self, payload: dict, *, now: float) -> dict:
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        fresh = {}
        for key, item in entries.items():
            if not isinstance(item, dict):
                continue
            created_at = float(item.get("created_at") or 0.0)
            if created_at > 0 and (now - created_at) > self._ttl_seconds:
                continue
            fresh[str(key)] = item
        payload["entries"] = fresh
        return payload

    def lookup(self, idempotency_key: str) -> dict:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return {}
        now = time.time()
        with self._lock:
            payload = self._prune_locked(self._load_locked(), now=now)
            entry = payload.get("entries", {}).get(normalized)
            self._save_locked(payload)
        return dict(entry or {}) if isinstance(entry, dict) else {}

    def remember(self, idempotency_key: str, *, task_id: str, text: str, bucket: str) -> None:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return
        now = time.time()
        with self._lock:
            payload = self._prune_locked(self._load_locked(), now=now)
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
            self._save_locked(payload)


def _generate_idempotency_store() -> _GenerateIdempotencyStore:
    path = str(_generate_idempotency_path())
    store = _GENERATE_IDEMPOTENCY_STORES.get(path)
    if store is None:
        store = _GenerateIdempotencyStore(Path(path), ttl_seconds=_generate_idempotency_ttl_seconds())
        _GENERATE_IDEMPOTENCY_STORES[path] = store
    return store


def create_app(
    *,
    allowed_origins,
    resolve_cors_origin,
    static_service,
    task_service,
    proxy_service,
    amap_config_js,
    geovis_config_js,
    coords_bulk_update,
) -> FastAPI:
    app = FastAPI(title="故事地图 API")

    allow_all = "*" in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        return JSONResponse(content={"ok": True, "service": "story_map", "version": "1"})

    @app.get("/health/ready")
    async def health_ready(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        payload = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        if not payload.get("ok"):
            structured_log(
                getattr(task_service, "_logger", None) or getattr(proxy_service, "_logger", None),
                "warning",
                "readiness_failed",
                alerts=payload.get("alerts"),
                serve_ready=payload.get("serve_ready"),
                generate_ready=payload.get("generate_ready"),
            )
        return JSONResponse(status_code=200 if payload.get("ok") else 503, content=payload)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return Response(
            content=_metrics_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/status", include_in_schema=False)
    async def star_office_status(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        return JSONResponse(status_code=200, content=_star_office_status_payload(task_service=task_service, readiness=readiness))

    @app.get("/agents", include_in_schema=False)
    async def star_office_agents(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        return JSONResponse(
            status_code=200,
            content=_star_office_agents_payload(task_service=task_service, readiness=readiness),
        )

    @app.get("/yesterday-memo", include_in_schema=False)
    async def star_office_memo(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        return JSONResponse(status_code=200, content=_star_office_memo_payload(task_service=task_service, readiness=readiness))

    @app.get("/health/runtime")
    async def health_runtime(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        payload = _runtime_health_snapshot(proxy_service, task_service=task_service)
        payload["service"] = "story_map"
        payload["version"] = "1"
        return JSONResponse(content=payload)

    @app.get("/debug_static")
    async def debug_static(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        return JSONResponse(content=static_service.debug_static_payload())

    @app.get("/amap-config.js", include_in_schema=False)
    async def amap_config(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return Response(content=amap_config_js(), media_type="application/javascript; charset=utf-8")

    @app.get("/geovis-config.js", include_in_schema=False)
    async def geovis_config(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return Response(content=geovis_config_js(), media_type="application/javascript; charset=utf-8")

    @app.get("/vendor/{name:path}", include_in_schema=False)
    async def vendor_asset(name: str, request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return static_service.vendor_response(name)

    @app.get("/task")
    async def get_task(id: str = "", debug: int = 0, request: FastAPIRequest = None) -> JSONResponse:
        if request is not None:
            _enforce_origin(request, resolve_cors_origin)
            if int(debug or 0):
                _enforce_runtime_debug_access(request)
        task_id = str(id or "").strip()
        if not task_id:
            return JSONResponse(status_code=400, content={"ok": False, "error": "id required"})
        snapshot = task_service.task_debug_snapshot(task_id) if int(debug or 0) else task_service.snapshot_task(task_id)
        status = 200 if snapshot.get("exists", snapshot.get("ok")) else 404
        return JSONResponse(status_code=status, content=snapshot)

    @app.get("/task/debug", include_in_schema=False)
    async def get_task_debug(id: str = "", request: FastAPIRequest = None) -> HTMLResponse:
        if request is not None:
            _enforce_origin(request, resolve_cors_origin)
            _enforce_runtime_debug_access(request)
        task_id = str(id or "").strip()
        if not task_id:
            return HTMLResponse(status_code=400, content="<h1>id required</h1>")
        snapshot = task_service.task_debug_snapshot(task_id)
        if not snapshot.get("exists", snapshot.get("ok")):
            return HTMLResponse(status_code=404, content="<h1>task not found</h1>")
        html = render_task_debug_html(snapshot, storage=task_service.storage_stats())
        return HTMLResponse(status_code=200, content=html)

    @app.get("/tasks")
    async def list_tasks(limit: int = 20, offset: int = 0, status: str = "", request: FastAPIRequest = None) -> JSONResponse:
        if request is not None:
            _enforce_origin(request, resolve_cors_origin)
            _enforce_runtime_debug_access(request)
        payload = task_service.list_tasks(limit=limit, offset=offset, status=status)
        return JSONResponse(status_code=200, content=payload)

    @app.get("/task/storage")
    async def get_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        return JSONResponse(status_code=200, content=task_service.storage_stats())

    @app.post("/task/storage/maintain")
    async def maintain_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.maintain_storage(
            prune_expired=bool(data.get("prune_expired", True)),
            vacuum=bool(data.get("vacuum", False)),
            reconcile=bool(data.get("reconcile", False)),
            auto_retry=bool(data.get("auto_retry", True)),
        )
        return JSONResponse(status_code=200, content=payload)

    @app.get("/generate")
    async def generate_get(request: FastAPIRequest, person: str = "", text: str = "") -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _ = person, text
        return JSONResponse(status_code=405, content={"ok": False, "error": "use POST /generate"})

    @app.post("/generate")
    async def generate_post(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        readiness = _build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        if not readiness.get("generate_ready"):
            structured_log(
                getattr(task_service, "_logger", None) or getattr(proxy_service, "_logger", None),
                "warning",
                "generate_rejected_unready",
                alerts=readiness.get("alerts"),
            )
            return JSONResponse(
                status_code=503,
                content={"ok": False, "error": "service not ready for generate", "readiness": readiness},
            )
        value = ""
        force = False
        if isinstance(data, dict):
            value = str(data.get("person") or data.get("text") or "").strip()
            force = bool(data.get("force"))
        if not value:
            return JSONResponse(status_code=400, content={"ok": False, "error": "person required"})
        idempotency_key = _request_idempotency_key(request, data)
        idempotency_hit = {}
        if idempotency_key:
            idempotency_hit = _generate_idempotency_store().lookup(idempotency_key)
            existing_task_id = str(idempotency_hit.get("task_id") or "").strip()
            if existing_task_id:
                snapshot = task_service.snapshot_task(existing_task_id)
                if snapshot.get("exists"):
                    return JSONResponse(
                        status_code=200,
                        content={
                            "ok": True,
                            "task_id": existing_task_id,
                            "queue": dict(snapshot.get("queue") or {}),
                            "deduped": True,
                            "idempotent": True,
                            "idempotency_key": idempotency_key,
                        },
                    )
        daily_limit = _generate_daily_limit()
        if daily_limit > 0:
            quota = _generate_daily_quota_store().consume(_request_client_bucket(request), daily_limit)
            if not quota.get("allowed"):
                return JSONResponse(
                    status_code=429,
                    content={
                        "ok": False,
                        "error": f"daily generate limit exceeded ({daily_limit}/day)",
                        "limit": daily_limit,
                        "used": quota.get("used", daily_limit),
                        "remaining": 0,
                        "reset_on": quota.get("reset_on"),
                    },
                )
        result = task_service.submit_task(value, dedupe=not force)
        if result.get("ok") and idempotency_key:
            _generate_idempotency_store().remember(
                idempotency_key,
                task_id=str(result.get("task_id") or "").strip(),
                text=value,
                bucket=_request_client_bucket(request),
            )
            result = {
                **dict(result),
                "idempotency_key": idempotency_key,
                "idempotent": bool(idempotency_hit),
            }
        status = 200 if result.get("ok") else 400
        return JSONResponse(status_code=status, content=result)

    @app.post("/task/cancel")
    async def cancel_task(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.cancel_task(str(data.get("id") or "").strip(), reason=str(data.get("reason") or "").strip())
        if payload.get("ok"):
            return JSONResponse(status_code=200, content=payload)
        error_text = str(payload.get("error") or "").strip().lower()
        status_code = 404 if "not found" in error_text else 409 if "already" in error_text else 400
        return JSONResponse(status_code=status_code, content=payload)

    @app.post("/task/retry")
    async def retry_task(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.retry_task(str(data.get("id") or "").strip(), reason=str(data.get("reason") or "").strip())
        if payload.get("ok"):
            return JSONResponse(status_code=200, content=payload)
        error_text = str(payload.get("error") or "").strip().lower()
        status_code = 404 if "not found" in error_text else 409 if "retryable" in error_text else 400
        return JSONResponse(status_code=status_code, content=payload)

    @app.post("/coords/bulk")
    async def coords_bulk(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = None
        status, payload = coords_bulk_update(data)
        return JSONResponse(status_code=status, content=payload)

    @app.post("/api/ai/proxy")
    async def ai_proxy(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = None
        if isinstance(data, dict) and bool(data.get("stream")):
            status, iterator = proxy_service.proxy_llm_stream(data)
            return StreamingResponse(
                iterator,
                status_code=status,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        status, payload = proxy_service.proxy_llm(data)
        return JSONResponse(status_code=status, content=payload)

    @app.get("/", include_in_schema=False)
    async def root_static(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return static_service.static_response("/")

    @app.get("/{requested_path:path}", include_in_schema=False)
    async def static_assets(requested_path: str, request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        return static_service.static_response("/" + str(requested_path or ""))

    return app


def run_server(app: FastAPI, port: int, logger) -> None:
    logger.info("server_start port=%s", port)
    print(f"故事地图智能分析服务已启动：http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
