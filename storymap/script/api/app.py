import json
import logging
_logger = logging.getLogger(__name__)
import os
import secrets
import time
import threading
import uvicorn
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pathlib import Path

from ..core.observability import structured_log
from ..runtime.task_debug import render_task_debug_html
from .health import build_readiness_payload, runtime_health_snapshot
from .metrics import build_metrics_payload
from .quota import (
    daily_limit_from_env,
    get_daily_quota_store,
    get_idempotency_store,
    request_client_bucket,
    request_idempotency_key,
)
from .star_office import (
    build_star_office_agents,
    build_star_office_memo,
    build_star_office_status,
    star_office_lang,
)

_RUNTIME_DEBUG_TOKEN_ENV_KEYS = ("STORYMAP_RUNTIME_DEBUG_TOKEN", "MAP_STORY_RUNTIME_DEBUG_TOKEN")
_RUNTIME_DEBUG_TOKEN_HEADER_KEYS = ("x-storymap-debug-token", "x-runtime-debug-token")
_DEBUG_EVENT_LOCK = threading.Lock()


def _first_env(*keys: str) -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return ""


def _enforce_origin(request: FastAPIRequest, resolve_cors_origin) -> None:
    origin = str(request.headers.get("origin", "") or "").strip()
    if origin.lower() == "null":
        origin = ""
    if origin and not resolve_cors_origin(origin):
        raise HTTPException(status_code=403, detail="origin not allowed")


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


def _sanitize_debug_session_id(raw: object) -> str:
    text = str(raw or "").strip().lower()
    filtered = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in text)
    filtered = "-".join(part for part in filtered.split("-") if part)
    return filtered[:80] or "default"


def _debug_log_file(session_id: object) -> Path:
    safe_session = _sanitize_debug_session_id(session_id)
    dbg_dir = Path(".dbg")
    dbg_dir.mkdir(parents=True, exist_ok=True)
    return dbg_dir / f"trae-debug-log-{safe_session}.ndjson"


def _append_debug_event(payload: object, request: FastAPIRequest) -> dict:
    item = dict(payload or {}) if isinstance(payload, dict) else {}
    session_id = _sanitize_debug_session_id(item.get("sessionId"))
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
    target = _debug_log_file(session_id)
    with _DEBUG_EVENT_LOCK:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def _read_debug_events(session_id: object, *, last: int = 50) -> list[dict]:
    target = _debug_log_file(session_id)
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
    portrait_service=None,
) -> FastAPI:
    app = FastAPI(
        title="故事地图 API",
        description=(
            "## 故事地图（StoryMap）后端 API 文档\n\n"
            "本服务为「历史人物时空分析」前端与外部脚本提供统一入口，主要能力包括：\n\n"
            "- **健康检查**：`/health`、`/health/ready`、`/health/runtime`，用于探活与依赖健康汇总。\n"
            "- **人物生成任务**：通过 `POST /generate` 提交人物名或问句，生成可交互的人物轨迹页与对话档案；通过 `/task`、`/tasks`、`/task/cancel`、`/task/retry` 管理异步任务生命周期。\n"
            "- **AI 对话代理**：`/api/ai/proxy` 提供模型推理代理，支持普通 JSON 与 Server-Sent Events 流式响应。\n"
            "- **地理编码补点**：`/coords/bulk` 批量刷新地图坐标与古今地名映射。\n"
            "- **静态资源**：根路径与人物页（`/<人物名>.html` 等）走 `/` 与 `/{path}` 静态分发。\n\n"
            "### 通用约定\n"
            "- 全部接口需在允许的 Origin 列表内（CORS 已配置）；调试接口另需运行时调试令牌。\n"
            "- 异步任务统一返回 `task_id`，客户端可通过 `GET /task?id=<task_id>` 轮询或订阅服务端事件获取进度。\n"
            "- 服务端在异常时返回结构化 JSON：`{ok: false, error, ...}`，请根据 HTTP 状态码与 `error` 字段做用户提示。\n"
        ),
        version="1.0.0",
        contact={"name": "故事地图团队", "url": "https://storymap.opendeploy.site"},
    )

    allow_all = "*" in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # GZip 压缩所有 JSON/HTML/CSS/JS 响应（704KB 首页数据可压缩至 ~100KB）
    app.add_middleware(GZipMiddleware, minimum_size=512)

    @app.get(
        "/health",
        tags=["健康检查"],
        summary="基础健康检查",
        description="返回服务的最简存活信息，常用于 Kubernetes / 负载均衡的 liveness 探针。无需鉴权。",
    )
    async def health(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        return JSONResponse(content={"ok": True, "service": "story_map", "version": "1"})

    @app.get(
        "/health/ready",
        tags=["健康检查"],
        summary="依赖就绪状态",
        description="汇总 LLM、地理编码、静态产物、任务队列等关键依赖的就绪状态。",
        responses={
            200: {"description": "所有关键依赖均可用，可以正常生成人物页与对话。"},
            503: {"description": "至少一个关键依赖未就绪，响应体 `alerts` 字段会列出告警明细。"},
        },
    )
    async def health_ready(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        payload = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
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
            content=build_metrics_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/status", include_in_schema=False)
    async def star_office_status(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        lang = star_office_lang(request.query_params.get("lang"))
        return JSONResponse(status_code=200, content=build_star_office_status(task_service=task_service, readiness=readiness, lang=lang))

    @app.get("/agents", include_in_schema=False)
    async def star_office_agents(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        return JSONResponse(
            status_code=200,
            content=build_star_office_agents(task_service=task_service, readiness=readiness),
        )

    @app.get("/yesterday-memo", include_in_schema=False)
    async def star_office_memo(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        lang = star_office_lang(request.query_params.get("lang"))
        return JSONResponse(status_code=200, content=build_star_office_memo(task_service=task_service, readiness=readiness, lang=lang))

    @app.get(
        "/health/runtime",
        tags=["健康检查"],
        summary="运行时详细健康快照",
        description="返回 LLM、地理编码、任务队列、housekeep 的完整指标。需提供运行时调试令牌（请求头 `x-storymap-debug-token` 或 `x-runtime-debug-token`）。",
    )
    async def health_runtime(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        payload = runtime_health_snapshot(proxy_service, task_service=task_service)
        payload["service"] = "story_map"
        payload["version"] = "1"
        return JSONResponse(content=payload)

    @app.post("/__debug/event", include_in_schema=False)
    async def debug_event_sink(request: FastAPIRequest) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as _exc:
            payload = {}
        event = _append_debug_event(payload, request)
        return JSONResponse(status_code=202, content={"ok": True, "stored": True, "sessionId": event.get("sessionId")})

    @app.get("/__debug/logs", include_in_schema=False)
    async def debug_logs(session: str = "", last: int = 50) -> JSONResponse:
        session_id = _sanitize_debug_session_id(session or "default")
        items = _read_debug_events(session_id, last=max(1, min(int(last or 50), 200)))
        return JSONResponse(content={"ok": True, "sessionId": session_id, "count": len(items), "items": items})

    @app.get(
        "/debug_static",
        tags=["调试"],
        summary="静态产物自检",
        description="返回 `artifacts/story_map` 目录、首页 `index.html` 是否存在等静态产物自检信息。需提供运行时调试令牌。",
    )
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

    @app.get(
        "/task",
        tags=["任务管理"],
        summary="查询单个任务状态",
        description="通过 `id` 查询一个异步人物生成任务的当前快照。`debug=1` 时返回包含内部调试字段的更详细快照（需调试令牌）。",
        responses={
            200: {"description": "任务存在并返回快照。"},
            404: {"description": "未找到对应任务，可能尚未入队或已被清理。"},
        },
    )
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

    @app.get(
        "/tasks",
        tags=["任务管理"],
        summary="列出任务（分页）",
        description="按 `status` 过滤并按时间倒序返回任务列表，`limit` 控制每页大小，`offset` 控制起始位置。需调试令牌。",
    )
    async def list_tasks(limit: int = 20, offset: int = 0, status: str = "", request: FastAPIRequest = None) -> JSONResponse:
        if request is not None:
            _enforce_origin(request, resolve_cors_origin)
            _enforce_runtime_debug_access(request)
        payload = task_service.list_tasks(limit=limit, offset=offset, status=status)
        return JSONResponse(status_code=200, content=payload)

    @app.get(
        "/task/storage",
        tags=["任务管理"],
        summary="任务存储后端状态",
        description="返回任务数据库当前大小、待清理条目数、最近一次 vacuum 时间等运维指标。需调试令牌。",
    )
    async def get_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        return JSONResponse(status_code=200, content=task_service.storage_stats())

    @app.post(
        "/task/storage/maintain",
        tags=["任务管理"],
        summary="维护任务存储",
        description="手动触发存储维护流程：清理过期任务、可选 `vacuum` 收缩文件、可选 `reconcile` 与状态机自洽校验、`auto_retry` 重新调度可重试任务。需调试令牌。",
    )
    async def maintain_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _enforce_runtime_debug_access(request)
        try:
            data = await request.json()
        except Exception as _exc:
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

    @app.get(
        "/generate",
        tags=["人物生成"],
        summary="生成接口占位说明",
        description="GET 形式仅作为提示，实际生成任务必须使用 `POST /generate` 提交。",
    )
    async def generate_get(request: FastAPIRequest, person: str = "", text: str = "") -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        _ = person, text
        return JSONResponse(status_code=405, content={"ok": False, "error": "use POST /generate"})

    @app.post(
        "/generate",
        tags=["人物生成"],
        summary="提交人物生成任务",
        description=(
            "接收人物名（如 `苏轼`）或自然语言问句（如 `对比李白与杜甫的游历路线`），"
            "异步生成可交互的人物轨迹页、GeoJSON、CSV 与对话档案。\n\n"
            "请求体支持以下字段：\n"
            "- `person`：人物名（与 `text` 二选一）\n"
            "- `text`：自然语言问句\n"
            "- `force`：是否忽略已有缓存结果，强制重新生成\n\n"
            "成功后返回 `task_id`，前端可通过 `/task?id=<task_id>` 轮询进度。"
            "当请求头携带 `Idempotency-Key` 时，服务端会按 key 去重，重复请求直接返回既有任务。"
        ),
        responses={
            200: {"description": "提交成功，返回 `task_id` 与任务状态。"},
            400: {"description": "请求体缺少 `person` 或 `text` 字段。"},
            429: {"description": "触发单日生成额度上限，可等待次日重试或联系管理员调整配额。"},
            503: {"description": "服务尚未就绪（依赖未通过健康检查）。"},
        },
    )
    async def generate_post(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
            data = {}
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
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
        idempotency_key = request_idempotency_key(request, data)
        idempotency_hit = {}
        if idempotency_key:
            idempotency_hit = get_idempotency_store().lookup(idempotency_key)
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
        daily_limit = daily_limit_from_env()
        if daily_limit > 0:
            quota = get_daily_quota_store().consume(request_client_bucket(request), daily_limit)
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
            get_idempotency_store().remember(
                idempotency_key,
                task_id=str(result.get("task_id") or "").strip(),
                text=value,
                bucket=request_client_bucket(request),
            )
            result = {
                **dict(result),
                "idempotency_key": idempotency_key,
                "idempotent": bool(idempotency_hit),
            }
        status = 200 if result.get("ok") else 400
        return JSONResponse(status_code=status, content=result)

    @app.post(
        "/task/cancel",
        tags=["任务管理"],
        summary="取消任务",
        description="请求体传入 `id` 与可选 `reason`，取消一个尚在排队或运行中的任务。已结束的任务无法取消。",
        responses={
            200: {"description": "取消请求已接受，任务进入取消流程。"},
            400: {"description": "请求体字段不合法。"},
            404: {"description": "未找到对应任务。"},
            409: {"description": "任务已经处于结束状态，无法取消。"},
        },
    )
    async def cancel_task(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.cancel_task(str(data.get("id") or "").strip(), reason=str(data.get("reason") or "").strip())
        if payload.get("ok"):
            return JSONResponse(status_code=200, content=payload)
        error_text = str(payload.get("error") or "").strip().lower()
        status_code = 404 if "not found" in error_text else 409 if "already" in error_text else 400
        return JSONResponse(status_code=status_code, content=payload)

    @app.post(
        "/task/retry",
        tags=["任务管理"],
        summary="重试任务",
        description="对失败或可重试的任务触发重新调度。请求体需传入 `id` 与可选 `reason`。",
        responses={
            200: {"description": "已重新入队，返回新的任务快照。"},
            400: {"description": "请求体字段不合法。"},
            404: {"description": "未找到对应任务。"},
            409: {"description": "当前任务状态不可重试（如已完成或正在运行）。"},
        },
    )
    async def retry_task(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.retry_task(str(data.get("id") or "").strip(), reason=str(data.get("reason") or "").strip())
        if payload.get("ok"):
            return JSONResponse(status_code=200, content=payload)
        error_text = str(payload.get("error") or "").strip().lower()
        status_code = 404 if "not found" in error_text else 409 if "retryable" in error_text else 400
        return JSONResponse(status_code=status_code, content=payload)

    @app.post(
        "/coords/bulk",
        tags=["地理编码"],
        summary="批量更新坐标",
        description="批量刷新地名坐标与古今地名映射，常用于补点脚本或人工校正。请求体格式参见 `/docs`。",
    )
    async def coords_bulk(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
            data = None
        status, payload = coords_bulk_update(data)
        return JSONResponse(status_code=status, content=payload)

    @app.post(
        "/api/ai/proxy",
        tags=["AI 对话"],
        summary="AI 模型推理代理",
        description=(
            "为前端对接 LLM 提供统一代理，避免在浏览器侧暴露明文 API Key。\n\n"
            "- 当请求体包含 `stream: true` 时，按 Server-Sent Events 流式输出增量结果。\n"
            "- 否则返回标准 JSON 响应。\n\n"
            "请求体与具体模型（默认 `MiniMax-M3`）保持兼容。"
        ),
    )
    async def ai_proxy(request: FastAPIRequest) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
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

    # ---------------- 人物肖像生成 ----------------
    def _resolve_portrait_service():
        if portrait_service is not None:
            return portrait_service
        try:
            from ..map import portrait_service as _portrait_service
            return _portrait_service
        except Exception as exc:
            return exc

    @app.get(
        "/portrait/status",
        tags=["人物肖像"],
        summary="肖像服务状态",
        description="返回当前生图模型、API 端点与本地缓存目录信息。",
    )
    async def portrait_status(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        svc = _resolve_portrait_service()
        if isinstance(svc, Exception):
            return JSONResponse(status_code=503, content={"ok": False, "error": f"portrait service unavailable: {svc}"})
        try:
            return JSONResponse(content=svc.portrait_status())
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    @app.post(
        "/portrait/generate",
        tags=["人物肖像"],
        summary="生成/获取人物肖像",
        description=(
            "按人物名生成艺术风格肖像（默认中国水墨画风格）。"
            "若本地已有缓存，则直接返回缓存文件，不消耗生图配额。\n\n"
            "请求体：\n"
            "- `name`（必填）：人物名\n"
            "- `dynasty`：所在朝代，用于风格提示\n"
            "- `title`：头衔/职业（如「诗仙」）\n"
            "- `short_bio`：≤ 200 字简介\n"
            "- `style`：`ink_wash` / `gongbi` / `realistic` / `cartoon`\n"
            "- `aspect_ratio`：`1:1` / `3:4` / `4:3` 等\n"
            "- `force`：是否忽略缓存强制重新生成\n"
            "- `n`：候选图数量（1-4）"
        ),
        responses={
            200: {"description": "成功，返回主图与（可选的）候选图 URL。"},
            400: {"description": "请求体缺少 `name` 字段。"},
            502: {"description": "调用生图接口失败。"},
            503: {"description": "生图服务未配置（缺少 API Key 等）。"},
        },
    )
    async def portrait_generate(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        svc = _resolve_portrait_service()
        if isinstance(svc, Exception):
            return JSONResponse(status_code=503, content={"ok": False, "error": f"portrait service unavailable: {svc}"})
        try:
            data = await request.json()
        except Exception as _exc:
            data = {}
        if not isinstance(data, dict):
            data = {}
        name = str(data.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "name required"})
        try:
            req_obj = svc.PortraitRequest(
                name=name,
                dynasty=str(data.get("dynasty") or "").strip(),
                title=str(data.get("title") or "").strip(),
                short_bio=str(data.get("short_bio") or "").strip()[:400],
                style=str(data.get("style") or "ink_wash").strip(),
                aspect_ratio=str(data.get("aspect_ratio") or "1:1").strip(),
            )
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        force = bool(data.get("force"))
        n = int(data.get("n") or 1)
        try:
            primary, candidates, from_cache = svc.generate_portrait(req_obj, force=force, n=n)
        except Exception as exc:
            structured_log(
                getattr(task_service, "_logger", None) or getattr(proxy_service, "_logger", None),
                "error",
                "portrait_generate_failed",
                name=name,
                dynasty=req_obj.dynasty,
                error=str(exc),
            )
            return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
        return JSONResponse(content={
            "ok": True,
            "name": name,
            "primary": f"/portrait/{name}",
            "primary_path": str(primary),
            "candidates": [f"/portrait/{name}?variant={idx}" for idx in range(2, len(candidates) + 2)],
            "from_cache": bool(from_cache),
            "style": req_obj.style,
            "dynasty": req_obj.dynasty,
        })

    @app.get(
        "/portrait/{name}",
        tags=["人物肖像"],
        summary="获取人物肖像文件",
        description="返回本地缓存的肖像 PNG。若 `variant=2|3|4` 指定候选图，则返回对应候选。",
    )
    async def portrait_file(name: str, request: FastAPIRequest, variant: int = 1) -> Response:
        _enforce_origin(request, resolve_cors_origin)
        svc = _resolve_portrait_service()
        if isinstance(svc, Exception):
            return JSONResponse(status_code=503, content={"ok": False, "error": f"portrait service unavailable: {svc}"})
        try:
            normalized_name = str(name or "").strip()
            for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
                if normalized_name.lower().endswith(ext):
                    normalized_name = normalized_name[: -len(ext)]
                    break
            primary = svc.portrait_cache_path(normalized_name)
            target = primary
            if int(variant or 1) > 1:
                base = svc.portrait_base_path(normalized_name)
                # 候选文件可能是 .jpg/.png 等多种扩展，扫描匹配
                stem = base.name + f"-{int(variant)}"
                matched = None
                for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    cand = base.with_name(stem + ext)
                    if cand.exists() and cand.stat().st_size > 0:
                        matched = cand
                        break
                target = matched or primary
            if not target.exists() or target.stat().st_size == 0:
                return JSONResponse(status_code=404, content={"ok": False, "error": "portrait not generated yet"})
            data = target.read_bytes()
            headers = {
                "Cache-Control": "public, max-age=86400",
            }
            suffix = target.suffix.lower()
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(suffix, "application/octet-stream")
            return Response(content=data, media_type=media_type, headers=headers)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

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
