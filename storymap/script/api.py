import uvicorn
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

try:
    from .story_task_debug import render_task_debug_html
except ImportError:
    from story_task_debug import render_task_debug_html


def _enforce_origin(request: FastAPIRequest, resolve_cors_origin) -> None:
    origin = request.headers.get("origin", "")
    if origin and not resolve_cors_origin(origin):
        raise HTTPException(status_code=403, detail="origin not allowed")


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

    @app.get("/debug_static")
    async def debug_static(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
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
        payload = task_service.list_tasks(limit=limit, offset=offset, status=status)
        return JSONResponse(status_code=200, content=payload)

    @app.get("/task/storage")
    async def get_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        return JSONResponse(status_code=200, content=task_service.storage_stats())

    @app.post("/task/storage/maintain")
    async def maintain_task_storage(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        payload = task_service.maintain_storage(
            prune_expired=bool(data.get("prune_expired", True)),
            vacuum=bool(data.get("vacuum", False)),
        )
        return JSONResponse(status_code=200, content=payload)

    @app.get("/generate")
    async def generate_get(request: FastAPIRequest, person: str = "", text: str = "") -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        value = str(person or text or "").strip()
        if not value:
            return JSONResponse(status_code=400, content={"ok": False, "error": "person required"})
        result = task_service.submit_task(value)
        status = 200 if result.get("ok") else 400
        return JSONResponse(status_code=status, content=result)

    @app.post("/generate")
    async def generate_post(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        value = ""
        if isinstance(data, dict):
            value = str(data.get("person") or data.get("text") or "").strip()
        if not value:
            return JSONResponse(status_code=400, content={"ok": False, "error": "person required"})
        result = task_service.submit_task(value)
        status = 200 if result.get("ok") else 400
        return JSONResponse(status_code=status, content=result)

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
    async def ai_proxy(request: FastAPIRequest) -> JSONResponse:
        _enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = None
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
