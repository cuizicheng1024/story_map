from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .common import enforce_origin


def create_router(*, resolve_cors_origin, proxy_service) -> APIRouter:
    router = APIRouter()

    @router.post(
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
        enforce_origin(request, resolve_cors_origin)
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

    return router
