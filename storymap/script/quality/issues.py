from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class QualityIssue:
    code: str
    type: str
    severity: str
    message: str
    field: str = ""
    auto_fixable: bool = False
    confidence: float = 1.0
    source: str = "quality"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["details"] is None:
            data["details"] = {}
        return data


def make_issue(
    code: str,
    issue_type: str,
    severity: str,
    message: str,
    *,
    field: str = "",
    auto_fixable: bool = False,
    confidence: float = 1.0,
    source: str = "quality",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return QualityIssue(
        code=code,
        type=issue_type,
        severity=severity,
        message=message,
        field=field,
        auto_fixable=auto_fixable,
        confidence=confidence,
        source=source,
        details=details or {},
    ).to_dict()


__all__ = ["QualityIssue", "make_issue"]
