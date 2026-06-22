from __future__ import annotations

import re
from typing import Dict, List, Sequence


def _match_known_person(text: object, known_people: Sequence[str]) -> str:
    content = str(text or "")
    if not content:
        return ""
    matched_name = ""
    matched_pos = -1
    matched_len = -1
    for name in known_people:
        cleaned = str(name or "").strip()
        if not cleaned:
            continue
        current_pos = content.rfind(cleaned)
        if current_pos < 0:
            continue
        current_len = len(cleaned)
        if current_pos > matched_pos or (current_pos == matched_pos and current_len > matched_len):
            matched_name = cleaned
            matched_pos = current_pos
            matched_len = current_len
    return matched_name


def extract_last_user(messages: List[Dict[str, object]]) -> str:
    last_user = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip() == "user":
            last_user = str(message.get("content") or "").strip()
    return last_user


def extract_system_text(messages: List[Dict[str, object]]) -> str:
    system_text = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip() == "system":
            system_text = str(message.get("content") or "")
    return system_text


def resolve_person_name(
    data: Dict[str, object],
    messages: List[Dict[str, object]],
    *,
    known_people: Sequence[str],
) -> str:
    context = data.get("context")
    if isinstance(context, dict):
        for key in ("personName", "person", "name"):
            value = str(context.get(key) or "").strip()
            if value:
                return value
    for key in ("person", "personName", "name"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    system_text = extract_system_text(messages)
    matched = re.search(r"扮演历史人物[:：]\s*([^\n。]+)", system_text)
    if matched:
        return matched.group(1).strip()
    matched_name = _match_known_person(system_text, known_people)
    if matched_name:
        return matched_name
    last_user = extract_last_user(messages)
    matched_name = _match_known_person(last_user, known_people)
    if matched_name:
        return matched_name
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip() != "user":
            continue
        matched_name = _match_known_person(message.get("content"), known_people)
        if matched_name:
            return matched_name
    return ""
