from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest
from fastapi.responses import HTMLResponse, JSONResponse

from ...runtime.task_debug import render_task_debug_html
from .common import enforce_origin, enforce_runtime_debug_access


def create_router(*, resolve_cors_origin, task_service) -> APIRouter:
    router = APIRouter()

    @router.get(
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
            enforce_origin(request, resolve_cors_origin)
            if int(debug or 0):
                enforce_runtime_debug_access(request)
        task_id = str(id or "").strip()
        if not task_id:
            return JSONResponse(status_code=400, content={"ok": False, "error": "id required"})
        snapshot = task_service.task_debug_snapshot(task_id) if int(debug or 0) else task_service.snapshot_task(task_id)
        status = 200 if snapshot.get("exists", snapshot.get("ok")) else 404
        return JSONResponse(status_code=status, content=snapshot)

    @router.get("/task/debug", include_in_schema=False)
    async def get_task_debug(id: str = "", request: FastAPIRequest = None) -> HTMLResponse:
        if request is not None:
            enforce_origin(request, resolve_cors_origin)
            enforce_runtime_debug_access(request)
        task_id = str(id or "").strip()
        if not task_id:
            return HTMLResponse(status_code=400, content="<h1>id required</h1>")
        snapshot = task_service.task_debug_snapshot(task_id)
        if not snapshot.get("exists", snapshot.get("ok")):
            return HTMLResponse(status_code=404, content="<h1>task not found</h1>")
        html = render_task_debug_html(snapshot, storage=task_service.storage_stats())
        return HTMLResponse(status_code=200, content=html)

    @router.get(
        "/tasks",
        tags=["任务管理"],
        summary="列出任务（分页）",
        description="按 `status` 过滤并按时间倒序返回任务列表，`limit` 控制每页大小，`offset` 控制起始位置。需调试令牌。",
    )
    async def list_tasks(limit: int = 20, offset: int = 0, status: str = "", request: FastAPIRequest = None) -> JSONResponse:
        if request is not None:
            enforce_origin(request, resolve_cors_origin)
            enforce_runtime_debug_access(request)
        payload = task_service.list_tasks(limit=limit, offset=offset, status=status)
        return JSONResponse(status_code=200, content=payload)

    @router.get(
        "/task/storage",
        tags=["任务管理"],
        summary="任务存储后端状态",
        description="返回任务数据库当前大小、待清理条目数、最近一次 vacuum 时间等运维指标。需调试令牌。",
    )
    async def get_task_storage(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        enforce_runtime_debug_access(request)
        return JSONResponse(status_code=200, content=task_service.storage_stats())

    @router.post(
        "/task/storage/maintain",
        tags=["任务管理"],
        summary="维护任务存储",
        description="手动触发存储维护流程：清理过期任务、可选 `vacuum` 收缩文件、可选 `reconcile` 与状态机自洽校验、`auto_retry` 重新调度可重试任务。需调试令牌。",
    )
    async def maintain_task_storage(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        enforce_runtime_debug_access(request)
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

    @router.post(
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
        enforce_origin(request, resolve_cors_origin)
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

    @router.post(
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
        enforce_origin(request, resolve_cors_origin)
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

    return router
