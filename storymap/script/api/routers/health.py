from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest, Response
from fastapi.responses import JSONResponse

from ...core.observability import structured_log
from ..health import build_readiness_payload, runtime_health_snapshot
from ..metrics import build_metrics_payload
from ..star_office import build_star_office_agents, build_star_office_memo, build_star_office_status, star_office_lang
from .common import enforce_origin, enforce_runtime_debug_access


def create_router(*, resolve_cors_origin, static_service, task_service, proxy_service) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/health",
        tags=["健康检查"],
        summary="基础健康检查",
        description="返回服务的最简存活信息，常用于 Kubernetes / 负载均衡的 liveness 探针。无需鉴权。",
    )
    async def health(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        return JSONResponse(content={"ok": True, "service": "story_map", "version": "1"})

    @router.get(
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
        enforce_origin(request, resolve_cors_origin)
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

    @router.get("/metrics", include_in_schema=False)
    async def metrics(request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        return Response(
            content=build_metrics_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @router.get("/status", include_in_schema=False)
    async def star_office_status(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        lang = star_office_lang(request.query_params.get("lang"))
        return JSONResponse(status_code=200, content=build_star_office_status(task_service=task_service, readiness=readiness, lang=lang))

    @router.get("/agents", include_in_schema=False)
    async def star_office_agents(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        return JSONResponse(
            status_code=200,
            content=build_star_office_agents(task_service=task_service, readiness=readiness),
        )

    @router.get("/yesterday-memo", include_in_schema=False)
    async def star_office_memo(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        readiness = build_readiness_payload(static_service=static_service, proxy_service=proxy_service, task_service=task_service)
        lang = star_office_lang(request.query_params.get("lang"))
        return JSONResponse(status_code=200, content=build_star_office_memo(task_service=task_service, readiness=readiness, lang=lang))

    @router.get(
        "/health/runtime",
        tags=["健康检查"],
        summary="运行时详细健康快照",
        description="返回 LLM、地理编码、任务队列、housekeep 的完整指标。需提供运行时调试令牌（请求头 `x-storymap-debug-token` 或 `x-runtime-debug-token`）。",
    )
    async def health_runtime(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        enforce_runtime_debug_access(request)
        payload = runtime_health_snapshot(proxy_service, task_service=task_service)
        payload["service"] = "story_map"
        payload["version"] = "1"
        return JSONResponse(content=payload)

    return router
