from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest, Response
from fastapi.responses import JSONResponse

from .common import enforce_origin


def create_router(*, resolve_cors_origin, static_service, amap_config_js, geovis_config_js) -> APIRouter:
    router = APIRouter()

    @router.get("/amap-config.js", include_in_schema=False)
    async def amap_config(request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        return Response(content=amap_config_js(), media_type="application/javascript; charset=utf-8")

    @router.get("/geovis-config.js", include_in_schema=False)
    async def geovis_config(request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        return Response(content=geovis_config_js(), media_type="application/javascript; charset=utf-8")

    @router.get("/vendor/{name:path}", include_in_schema=False)
    async def vendor_asset(name: str, request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        return static_service.vendor_response(name)

    @router.get("/assets/auth/status", include_in_schema=False)
    async def asset_auth_status(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        return JSONResponse(status_code=200, content={"ok": True, "authed": False})

    @router.get("/assets/list", include_in_schema=False)
    async def asset_list(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        return JSONResponse(status_code=200, content={"ok": True, "items": []})

    @router.get("/", include_in_schema=False)
    async def root_static(request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        try:
            return static_service.static_response("/")
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return static_service.static_response("/index.html")
            raise

    @router.get("/{requested_path:path}", include_in_schema=False)
    async def static_assets(requested_path: str, request: FastAPIRequest) -> Response:
        enforce_origin(request, resolve_cors_origin)
        return static_service.static_response("/" + str(requested_path or ""))

    return router
