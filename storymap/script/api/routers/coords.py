from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from .common import enforce_origin


def create_router(*, resolve_cors_origin, coords_bulk_update) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/coords/bulk",
        tags=["地理编码"],
        summary="批量更新坐标",
        description="批量刷新地名坐标与古今地名映射，常用于补点脚本或人工校正。请求体格式参见 `/docs`。",
    )
    async def coords_bulk(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception as _exc:
            data = None
        status, payload = coords_bulk_update(data)
        return JSONResponse(status_code=status, content=payload)

    return router
