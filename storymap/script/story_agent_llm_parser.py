from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

try:
    from .story_agent_state import AgentIssue
except ImportError:
    from story_agent_state import AgentIssue


def strip_code_fences(text: str) -> str:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", body)
        body = re.sub(r"\n?```$", "", body)
    return body.strip()


def parse_json_payload(text: str) -> Optional[Dict[str, object]]:
    body = strip_code_fences(text)
    if not body:
        return None
    candidates = [body]
    match = re.search(r"(\{[\s\S]*\})", body)
    if match:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def coerce_issue(
    *,
    field: str,
    claim: str,
    correction: str,
    confidence: float,
    reason: str,
) -> AgentIssue:
    return {
        "field": field,
        "claim": claim,
        "correction": correction,
        "confidence": round(float(confidence), 3),
        "reason": reason,
    }


def coerce_issue_list(raw_issues: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    if not isinstance(raw_issues, list):
        return issues
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(
            coerce_issue(
                field=str(item.get("field") or "other"),
                claim=str(item.get("claim") or ""),
                correction=str(item.get("correction") or ""),
                confidence=float(item.get("confidence") or 0.0),
                reason=str(item.get("reason") or ""),
            )
        )
    return issues


__all__ = [
    "coerce_issue",
    "coerce_issue_list",
    "parse_json_payload",
    "strip_code_fences",
]
