from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from ...core.observability import structured_log
from ...core.person_registry import canonical_person_name, normalize_person_token
from ...core.public_url import public_url
from ..health import build_readiness_payload
from ..quota import (
    daily_limit_from_env,
    get_daily_quota_store,
    get_idempotency_store,
    request_client_bucket,
    request_idempotency_key,
)
from .common import enforce_origin


_FICTIONAL_MARKERS = ("孙悟空", "猪八戒", "沙和尚", "唐僧", "贾宝玉", "林黛玉", "虚构", "小说", "动漫", "游戏角色")
_SENSITIVE_MARKERS = ("现任", "总统", "主席", "总理", "明星", "网红", "演员", "歌手")
_MULTI_PERSON_SPLIT_MARKERS = ("和", "与", "、", ",", "，")


def _clean_precheck_input(value: object) -> str:
    return str(value or "").strip().strip("。.!！?？")


def _load_homepage_people(static_service) -> dict[str, object]:
    roots = []
    try:
        payload = static_service.debug_static_payload()
        roots = [str(item or "").strip() for item in payload.get("static_dirs") or [] if str(item or "").strip()]
        active = str(payload.get("static_dir") or "").strip()
        if active:
            roots.insert(0, active)
    except Exception:
        roots = []

    nodes: list[dict] = []
    for root in roots:
        path = Path(root) / "stellar_home_data.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        raw_nodes = data.get("nodes") if isinstance(data, dict) else None
        if isinstance(raw_nodes, list):
            nodes = [item for item in raw_nodes if isinstance(item, dict)]
            break

    by_token: dict[str, dict] = {}
    known_names: list[str] = []
    for node in nodes:
        name = str(node.get("person") or "").strip()
        if not name:
            continue
        known_names.append(name)
        keys = [name]
        aliases = node.get("aliases")
        if isinstance(aliases, list):
            keys.extend(str(item or "").strip() for item in aliases)
        search_keys = node.get("search_keys")
        if isinstance(search_keys, list):
            keys.extend(str(item or "").strip() for item in search_keys)
        for key in keys:
            token = normalize_person_token(key)
            if token and token not in by_token:
                by_token[token] = node
    return {"nodes": nodes, "by_token": by_token, "known_names": known_names}


def _existing_person_url(static_service, name: str) -> str:
    person = str(name or "").strip()
    if not person:
        return ""
    try:
        target = static_service.static_target_path(f"/{person}.html")
    except Exception:
        target = None
    if target is None:
        return ""
    return f"./{quote(person)}.html"


def _build_precheck_payload(static_service, value: object) -> dict[str, object]:
    raw = _clean_precheck_input(value)
    if not raw:
        return {"ok": False, "allowed": False, "status": "empty", "reason": "请输入人物名"}

    if any(marker in raw for marker in _FICTIONAL_MARKERS):
        return {
            "ok": True,
            "input": raw,
            "normalized": raw,
            "allowed": False,
            "status": "blocked",
            "type": "fictional_or_literary_character",
            "reason": "该输入更像文学/虚构人物，暂不建议生成真实历史足迹",
            "confidence": 0.86,
        }
    if any(marker in raw for marker in _SENSITIVE_MARKERS):
        return {
            "ok": True,
            "input": raw,
            "normalized": raw,
            "allowed": False,
            "status": "blocked",
            "type": "unsupported_modern_person",
            "reason": "当前产品主要面向历史人物，暂不支持现代敏感或娱乐人物生成",
            "confidence": 0.72,
        }
    if sum(1 for marker in _MULTI_PERSON_SPLIT_MARKERS if marker in raw) and len(raw) >= 5:
        return {
            "ok": True,
            "input": raw,
            "normalized": raw,
            "allowed": True,
            "status": "multi_person",
            "type": "multi_person_query",
            "mode": "comparison_or_multi_generate",
            "reason": "检测到可能包含多个人物，将进入多人物分析流程",
            "confidence": 0.7,
        }

    people = _load_homepage_people(static_service)
    known_names = list(people.get("known_names") or [])
    canonical = canonical_person_name(raw, known_names) or raw
    token = normalize_person_token(canonical)
    node = dict((people.get("by_token") or {}).get(token) or {})
    if not node:
        raw_token = normalize_person_token(raw)
        node = dict((people.get("by_token") or {}).get(raw_token) or {})
        if node.get("person"):
            canonical = str(node.get("person") or canonical).strip()

    page_name = str(node.get("person") or canonical).strip()
    url = _existing_person_url(static_service, page_name)
    if url:
        absolute_url = public_url(url)
        payload = {
            "ok": True,
            "input": raw,
            "normalized": page_name,
            "allowed": True,
            "status": "cached",
            "type": "historical_person",
            "mode": "open_cached_page",
            "cached": True,
            "can_open": True,
            "url": url,
            "reason": "已收录人物页，可直接秒开",
            "confidence": 0.98,
            "person": {
                "name": page_name,
                "dynasty": node.get("dynasty") or "",
                "birth_year": node.get("birth_year"),
                "death_year": node.get("death_year"),
                "aliases": node.get("aliases") if isinstance(node.get("aliases"), list) else [],
                "file": node.get("file") or f"{page_name}.html",
            },
        }
        if absolute_url:
            payload["public_url"] = absolute_url
        return payload

    return {
        "ok": True,
        "input": raw,
        "normalized": canonical,
        "allowed": True,
        "status": "generatable",
        "type": "historical_person_candidate",
        "mode": "generate_full",
        "cached": False,
        "can_open": False,
        "reason": "本地暂未命中已有人物页，将尝试生成新足迹",
        "confidence": 0.62,
        "person": {"name": canonical},
    }


def create_router(*, resolve_cors_origin, static_service, task_service, proxy_service) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/generate",
        tags=["人物生成"],
        summary="生成接口占位说明",
        description="GET 形式仅作为提示，实际生成任务必须使用 `POST /generate` 提交。",
    )
    async def generate_get(request: FastAPIRequest, person: str = "", text: str = "") -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        _ = person, text
        return JSONResponse(status_code=405, content={"ok": False, "error": "use POST /generate"})

    @router.post(
        "/generate/precheck",
        tags=["人物生成"],
        summary="人物生成前准入判断",
        description="判断输入是否适合生成，并在已收录 500+ 人物中命中时返回可秒开的缓存页面 URL。",
    )
    async def generate_precheck(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
        try:
            data = await request.json()
        except Exception:
            data = {}
        value = ""
        if isinstance(data, dict):
            value = str(data.get("person") or data.get("text") or "").strip()
        payload = _build_precheck_payload(static_service, value)
        status = 200 if payload.get("ok") else 400
        return JSONResponse(status_code=status, content=payload)

    @router.post(
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
            403: {},
            503: {"description": "服务尚未就绪（依赖未通过健康检查）。"},
            404: {},
        },
    )
    async def generate_post(request: FastAPIRequest) -> JSONResponse:
        enforce_origin(request, resolve_cors_origin)
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

    return router
