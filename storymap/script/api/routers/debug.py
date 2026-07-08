from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from .common import append_debug_event, enforce_origin, enforce_runtime_debug_access, read_debug_events, sanitize_debug_session_id


def create_router(*, resolve_cors_origin, static_service) -> APIRouter:
    router = APIRouter()

    @router.post("/__debug/event", include_in_schema=False)
    async def debug_event_sink(request: FastAPIRequest) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as _exc:
            payload = {}
        event = append_debug_event(payload, request)
        return JSONResponse(status_code=202, content={"ok": True, "stored": True, "sessionId": event.get("sessionId")})

    @router.get("/__debug/logs", include_in_schema=False)
    async def debug_logs(session: str = "", last: int = 50) -> JSONResponse:
        session_id = sanitize_debug_session_id(session or "default")
        items = read_debug_events(session_id, last=max(1, min(int(last or 50), 200)))
        return JSONResponse(content={"ok": True, "sessionId": session_id, "count": len(items), "items": items})

    @router.get(
        "/debug_static",
        tags=["调试"],
        summary="静态产物自检",
        description="返回 `artifacts/story_map` 目录、首页 `index.html` 是否存在等静态产物自检信息。需提供运行时调试令牌。",
    )
    async def debug_static(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        enforce_runtime_debug_access(request)
        return JSONResponse(content=static_service.debug_static_payload())

    return router
