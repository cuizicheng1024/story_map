from __future__ import annotations

from fastapi import APIRouter, Request as FastAPIRequest, Response
from fastapi.responses import JSONResponse

from ...core.observability import structured_log
from .common import enforce_origin


def create_router(*, resolve_cors_origin, task_service, proxy_service, portrait_service=None) -> APIRouter:
    router = APIRouter()

    def _resolve_portrait_service():
        if portrait_service is not None:
            return portrait_service
        try:
            from ...map import portrait_service as _portrait_service
            return _portrait_service
        except Exception as exc:
            return exc

    @router.get(
        "/portrait/status",
        tags=["人物肖像"],
        summary="肖像服务状态",
        description="返回当前生图模型、API 端点与本地缓存目录信息。",
    )
    async def portrait_status(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        svc = _resolve_portrait_service()
        if isinstance(svc, Exception):
            return JSONResponse(status_code=503, content={"ok": False, "error": f"portrait service unavailable: {svc}"})
        try:
            return JSONResponse(content=svc.portrait_status())
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    @router.post(
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
        enforce_origin(request, resolve_cors_origin)
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

    @router.get(
        "/portrait/{name}",
        tags=["人物肖像"],
        summary="获取人物肖像文件",
        description="返回本地缓存的肖像 PNG。若 `variant=2|3|4` 指定候选图，则返回对应候选。",
    )
    async def portrait_file(name: str, request: FastAPIRequest, variant: int = 1) -> Response:
        enforce_origin(request, resolve_cors_origin)
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

    return router
