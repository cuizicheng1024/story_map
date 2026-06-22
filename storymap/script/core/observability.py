from __future__ import annotations

import json
import logging
import math
import time
from typing import Dict, Iterable, List, Tuple


def structured_log(logger: object, level: str, event: str, **fields: object) -> None:
    target = getattr(logger, str(level or "info").lower(), None)
    if not callable(target):
        target = getattr(logger, "info", None)
    if not callable(target):
        return
    payload = {
        "ts": round(time.time(), 3),
        "event": str(event or "").strip() or "event",
    }
    for key, value in fields.items():
        if value is None:
            continue
        payload[str(key)] = _normalize_log_value(value)
    target(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _normalize_log_value(value: object) -> object:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 6)
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_log_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_log_value(item) for item in value]
    return str(value)


def prometheus_escape(value: object) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def prometheus_labels(labels: Dict[str, object]) -> str:
    items: List[Tuple[str, object]] = [(str(key), value) for key, value in labels.items() if str(key).strip()]
    if not items:
        return ""
    rendered = ",".join(f'{key}="{prometheus_escape(value)}"' for key, value in sorted(items))
    return "{" + rendered + "}"


def prometheus_lines(
    metric_name: str,
    value: object,
    *,
    labels: Dict[str, object] | None = None,
    metric_type: str = "gauge",
    help_text: str = "",
) -> List[str]:
    safe_name = str(metric_name or "").strip()
    if not safe_name:
        return []
    lines: List[str] = []
    if help_text:
        lines.append(f"# HELP {safe_name} {help_text}")
    if metric_type:
        lines.append(f"# TYPE {safe_name} {metric_type}")
    normalized_value = value
    if isinstance(value, bool):
        normalized_value = 1 if value else 0
    elif isinstance(value, float):
        normalized_value = round(value, 6) if math.isfinite(value) else 0
    elif isinstance(value, int):
        normalized_value = value
    else:
        try:
            normalized_value = float(value)
            if math.isfinite(normalized_value):
                normalized_value = round(normalized_value, 6)
            else:
                normalized_value = 0
        except Exception:
            normalized_value = 0
    lines.append(f"{safe_name}{prometheus_labels(labels or {})} {normalized_value}")
    return lines


__all__ = ["prometheus_escape", "prometheus_labels", "prometheus_lines", "structured_log"]
