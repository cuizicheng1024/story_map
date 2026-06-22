from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from ..core.project_paths import classify_story_person_authenticity, known_authentic_person_names, story_person_names

_TASK_LIKE_TOKENS = (
    "为什么",
    "为何",
    "如何",
    "怎么",
    "请",
    "帮我",
    "比较",
    "对比",
    "分析",
    "总结",
    "解释",
    "给我",
    "什么",
    "哪里",
    "哪儿",
    "谁",
    "轨迹",
    "足迹",
    "证据",
    "活动",
)


def looks_like_person_atom(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) > 12:
        return False
    if re.search(r"[?？!！。:：；;（）()\[\]{}<>]", cleaned):
        return False
    return not any(token in cleaned for token in _TASK_LIKE_TOKENS)


def _split_candidate_parts(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"[、，,\s]+", str(text or "").strip()) if part.strip()]


def _load_known_people(story_dir: str) -> Set[str]:
    try:
        return set(story_person_names(story_dir))
    except Exception:
        return set()


def _load_known_authentic_people(story_dir: str, known_people: Set[str]) -> Set[str]:
    try:
        return set(known_authentic_person_names(story_dir=Path(story_dir)))
    except Exception:
        return set(known_people)


@dataclass(frozen=True)
class ResolvedTaskTargets:
    client: Optional[object]
    resolved_targets: List[str]
    generation_targets: List[str]
    blocked_results: List[Dict[str, object]] = field(default_factory=list)
    error_message: str = ""


def resolve_task_targets(
    *,
    text: str,
    project_root: Callable[[], str],
    get_llm_client: Callable[..., object],
    extract_historical_figures: Callable[[object, str], List[str]],
    timeout_seconds: Callable[[], int],
    ensure_can_continue: Callable[[], None],
    append_progress: Callable[[str, str], None],
    llm_event: Callable[[str], None],
) -> ResolvedTaskTargets:
    text_clean = str(text or "").strip()
    explicit_single_person_input = looks_like_person_atom(text_clean)
    story_dir = str(project_root() or "")
    story_dir = f"{story_dir}/storymap/examples/story" if story_dir else ""
    known_people = _load_known_people(story_dir)
    known_authentic_people = _load_known_authentic_people(story_dir, known_people)

    targets: List[str] = []
    targets_from_extraction = False
    if text_clean and text_clean in known_people:
        targets = [text_clean]
        append_progress("识别任务对象", f"命中本地人物档案：{text_clean}")
    else:
        parts = _split_candidate_parts(text_clean)
        if parts and all(part in known_people for part in parts) and len(parts) >= 2:
            targets = parts[:10]
            append_progress("识别任务对象", f"命中本地人物档案：{'、'.join(targets)}")

    client: Optional[object] = None
    if not targets:
        ensure_can_continue()
        client = get_llm_client(event_callback=llm_event, timeout_resolver=timeout_seconds)
        targets = extract_historical_figures(client, text)
        targets_from_extraction = bool(targets)

    if not targets:
        fallback_parts = _split_candidate_parts(text)
        if len(fallback_parts) >= 2 and all(looks_like_person_atom(part) for part in fallback_parts):
            targets = fallback_parts[:10]
            append_progress("识别任务对象", f"未命中档案，已按输入人物列表处理：{'、'.join(targets)}")
        elif looks_like_person_atom(text_clean):
            targets = [text_clean]
            append_progress("识别任务对象", f"未命中档案，已按输入人物处理：{text_clean}")
        else:
            return ResolvedTaskTargets(
                client=client,
                resolved_targets=[],
                generation_targets=[],
                error_message="未识别到人物，请输入人物姓名，或先进入人物页再提问。",
            )

    resolved_targets = list(targets)
    blocked_targets = [
        person
        for person in targets
        if (
            not classify_story_person_authenticity(person, story_dir)[0]
            or (
                targets_from_extraction
                and not explicit_single_person_input
                and person not in known_authentic_people
            )
        )
    ]

    blocked_results: List[Dict[str, object]] = []
    if blocked_targets:
        error_message = f"已拦截非真实或存疑人物：{'、'.join(blocked_targets[:3])}"
        append_progress("真实性过滤", error_message)
        blocked_results = [
            {
                "ok": False,
                "status": "failed",
                "person": person,
                "error": f"已拦截非真实或存疑人物：{person}",
            }
            for person in blocked_targets
        ]
        targets = [person for person in targets if person not in blocked_targets]
        if not targets:
            return ResolvedTaskTargets(
                client=client,
                resolved_targets=resolved_targets,
                generation_targets=[],
                blocked_results=blocked_results,
                error_message=error_message,
            )

    return ResolvedTaskTargets(
        client=client,
        resolved_targets=resolved_targets,
        generation_targets=list(targets),
        blocked_results=blocked_results,
        error_message="",
    )


__all__ = ["ResolvedTaskTargets", "looks_like_person_atom", "resolve_task_targets"]
