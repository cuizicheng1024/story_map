"""Star Office 状态展示模块。

将任务队列状态映射为「橙子科技公司」办公场景的 Agent 状态、公告与备忘录，
供首页前端渲染实时办公动画。文案配置位于 data/corpus/star_office_copy.json。
"""
from __future__ import annotations

import json
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from storymap.script.core.project_paths import data_corpus_file_path


@lru_cache(maxsize=1)
def _load_copy() -> Dict[str, object]:
    """加载 Star Office 文案配置（data/corpus/star_office_copy.json）。"""
    config_path = data_corpus_file_path("star_office_copy.json")
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


_STAR_OFFICE_NAME = "橙子科技公司"
_COPY: Dict[str, str] = (_load_copy().get("copy") or {}) if _load_copy() else {}


def star_office_lang(lang: str | None) -> str:
    """返回 'zh'（仅保留中文支持）。"""
    return "zh"


def star_office_copy(key: str, *, lang: str = "zh", **kwargs: object) -> str:
    """获取中文文案模板并进行格式化。"""
    _ = lang
    template = str(_COPY.get(key) or key)
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


# ── Task query helpers ──────────────────────────────────────────────────

def _list_task_items(task_service: object, *, status: str = "", limit: int = 1) -> list[dict]:
    if not hasattr(task_service, "list_tasks") or not callable(getattr(task_service, "list_tasks")):
        return []
    try:
        payload = dict(getattr(task_service, "list_tasks")(limit=limit, offset=0, status=status) or {})
    except Exception:
        return []
    return [dict(item) for item in list(payload.get("tasks") or []) if isinstance(item, dict)]


def _task_updated_at(task: dict) -> float:
    try:
        return float(task.get("updated_at") or task.get("created_at") or 0.0)
    except Exception:
        return 0.0


def _task_person_label(task: dict, *, default: str = "历史人物") -> str:
    people = [str(item).strip() for item in list(task.get("people") or []) if str(item).strip()]
    text = str(task.get("text") or "").strip()
    return people[0] if people else (text or default)


def _list_recent_task_items(task_service: object, *, limit: int = 8) -> list[dict]:
    return _list_task_items(task_service, status="", limit=limit)


def _pick_task_by_statuses(items: list[dict], *statuses: str) -> dict:
    normalized = {str(item).strip() for item in statuses if str(item).strip()}
    if not normalized:
        return {}
    for item in items:
        if str(item.get("status") or "").strip() in normalized:
            return dict(item)
    return {}


def _is_recent_task(task: dict, *, window_seconds: int = 900) -> bool:
    updated_at = _task_updated_at(task)
    return updated_at > 0 and (time.time() - updated_at) <= max(int(window_seconds), 60)


def _star_office_task_context(task_service: object) -> dict:
    recent = _list_recent_task_items(task_service, limit=8)
    active = _pick_task_by_statuses(recent, "running", "queued")
    latest_success = _pick_task_by_statuses(recent, "completed")
    latest_failure = _pick_task_by_statuses(recent, "failed", "partial_failed", "timed_out", "cancelled", "interrupted")
    latest_any = dict(recent[0]) if recent else {}
    return {
        "recent": recent,
        "active": active,
        "latest_success": latest_success,
        "latest_failure": latest_failure,
        "latest_any": latest_any,
    }


def _pick_latest_task(*tasks: dict) -> dict:
    picked: dict = {}
    picked_updated_at = -1.0
    for task in tasks:
        current = dict(task or {})
        if not current:
            continue
        updated_at = _task_updated_at(current)
        if updated_at >= picked_updated_at:
            picked = current
            picked_updated_at = updated_at
    return picked


def _build_star_office_agent(*, agent_id: str, name: str, state: str, auth_status: str, area: str, avatar: str) -> dict:
    return {
        "agentId": str(agent_id).strip(),
        "name": str(name).strip(),
        "state": str(state).strip() or "idle",
        "authStatus": str(auth_status).strip() or "approved",
        "area": str(area).strip() or "breakroom",
        "avatar": str(avatar).strip() or "guest_role_1",
    }


# ── Public payload builders ─────────────────────────────────────────────

def build_star_office_status(*, task_service: object, readiness: dict, lang: str = "zh") -> dict:
    lang = star_office_lang(lang)
    context = _star_office_task_context(task_service)
    task = dict(context.get("active") or {})
    status = str(task.get("status") or "").strip()
    label = _task_person_label(task)
    if not readiness.get("serve_ready"):
        return {
            "state": "idle",
            "detail": star_office_copy("status_serve_recovering", lang=lang),
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if not readiness.get("generate_ready"):
        return {
            "state": "idle",
            "detail": star_office_copy("status_generate_paused", lang=lang),
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    if status == "running":
        return {
            "state": "executing",
            "detail": star_office_copy("status_running", lang=lang, label=label),
            "progress": 62,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if status == "queued":
        return {
            "state": "researching",
            "detail": star_office_copy("status_queued", lang=lang, label=label),
            "progress": 18,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if latest_terminal and str(latest_terminal.get("status") or "").strip() == "completed":
        success_label = _task_person_label(latest_terminal)
        success_state = "syncing" if _is_recent_task(latest_terminal, window_seconds=900) else "idle"
        return {
            "state": success_state,
            "detail": star_office_copy("status_recent_success_active", lang=lang, label=success_label),
            "progress": 100 if success_state == "syncing" else 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    if latest_terminal:
        failed_label = _task_person_label(latest_terminal)
        detail = str(latest_terminal.get("error") or "").strip()
        summary = star_office_copy("status_recent_failure", lang=lang, label=failed_label)
        if detail:
            summary = star_office_copy("status_recent_failure_with_detail", lang=lang, summary=summary, detail=detail)
        return {
            "state": "idle",
            "detail": summary,
            "progress": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "officeName": _STAR_OFFICE_NAME,
        }
    return {
        "state": "idle",
        "detail": star_office_copy("status_idle", lang=lang),
        "progress": 0,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "officeName": _STAR_OFFICE_NAME,
    }


def build_star_office_agents(*, task_service: object, readiness: dict) -> list[dict]:
    context = _star_office_task_context(task_service)
    active = dict(context.get("active") or {})
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    agents: list[dict] = []

    def add_agent(agent_id: str, name: str, state: str, *, auth_status: str = "approved", area: str = "", avatar: str = "") -> None:
        normalized_id = str(agent_id).strip()
        if not normalized_id or any(str(item.get("agentId") or "").strip() == normalized_id for item in agents):
            return
        agents.append(
            _build_star_office_agent(
                agent_id=normalized_id,
                name=name,
                state=state,
                auth_status=auth_status,
                area=area,
                avatar=avatar,
            )
        )

    if not readiness.get("serve_ready"):
        add_agent("site-guard", "站点守护 Agent", "idle", area="breakroom", avatar="guest_role_5")
        add_agent("recover-agent", "恢复巡检 Agent", "researching", area="writing", avatar="guest_role_4")
        return agents

    active_status = str(active.get("status") or "").strip()
    if active_status == "running":
        add_agent("orange-agent", "橙子 Agent", "executing", area="writing", avatar="guest_role_1")
        add_agent("dispatch-agent", "排队调度 Agent", "researching", area="researching", avatar="guest_role_3")
        return agents
    if active_status == "queued":
        add_agent("dispatch-agent", "排队调度 Agent", "researching", area="researching", avatar="guest_role_3")
        add_agent("orange-agent", "橙子 Agent", "idle", area="breakroom", avatar="guest_role_1")
        return agents

    if (
        latest_terminal
        and str(latest_terminal.get("status") or "").strip() == "completed"
        and _is_recent_task(latest_terminal, window_seconds=900)
    ):
        add_agent("sync-agent", "发布同步 Agent", "syncing", area="writing", avatar="guest_role_2")
    elif latest_terminal and _is_recent_task(latest_terminal, window_seconds=900):
        add_agent("recover-agent", "恢复巡检 Agent", "error", area="error", avatar="guest_role_4")

    if readiness.get("generate_ready"):
        add_agent("reception-agent", "前台接待 Agent", "idle", area="breakroom", avatar="guest_role_6")
        add_agent("archive-agent", "档案整理 Agent", "idle", area="breakroom", avatar="guest_role_5")
    else:
        add_agent("dependency-agent", "依赖巡检 Agent", "researching", area="writing", avatar="guest_role_4")
        add_agent("reception-agent", "前台接待 Agent", "idle", area="breakroom", avatar="guest_role_6")
    return agents[:3]


def build_star_office_memo(*, task_service: object, readiness: dict, lang: str = "zh") -> dict:
    lang = star_office_lang(lang)
    context = _star_office_task_context(task_service)
    active = dict(context.get("active") or {})
    latest_success = dict(context.get("latest_success") or {})
    latest_failure = dict(context.get("latest_failure") or {})
    latest_terminal = _pick_latest_task(latest_success, latest_failure)
    active_status = str(active.get("status") or "").strip()
    if active_status == "running":
        memo = star_office_copy("memo_running", lang=lang, label=_task_person_label(active))
    elif active_status == "queued":
        memo = star_office_copy("memo_queued", lang=lang, label=_task_person_label(active))
    elif latest_terminal and str(latest_terminal.get("status") or "").strip() == "completed":
        memo = star_office_copy("memo_success", lang=lang, label=_task_person_label(latest_terminal))
    elif latest_terminal:
        memo = star_office_copy("memo_failure", lang=lang, label=_task_person_label(latest_terminal))
    else:
        memo = star_office_copy("memo_idle", lang=lang)
    if not readiness.get("generate_ready"):
        memo += star_office_copy("memo_paused_suffix", lang=lang)
    return {"success": True, "date": str(date.today()), "memo": memo}


__all__ = [
    "build_star_office_agents",
    "build_star_office_memo",
    "build_star_office_status",
    "star_office_lang",
]
