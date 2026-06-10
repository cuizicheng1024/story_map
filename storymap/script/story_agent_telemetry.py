from __future__ import annotations

from typing import Callable, Dict, List, Tuple, TypedDict


class MemoryAccess(TypedDict, total=False):
    bucket: str
    hit: bool


def set_memory_access(func: Callable[..., object], *, bucket: str, hit: bool) -> None:
    try:
        setattr(func, "__memory_last_access__", {"bucket": str(bucket or "").strip(), "hit": bool(hit)})
    except Exception:
        return


def consume_memory_access(func: Callable[..., object]) -> MemoryAccess:
    access = getattr(func, "__memory_last_access__", None)
    try:
        setattr(func, "__memory_last_access__", None)
    except Exception:
        pass
    return dict(access) if isinstance(access, dict) else {}


def attach_memory_access_to_trace(
    tool_traces: List[Dict[str, object]],
    *,
    previous_trace_count: int,
    access: Dict[str, object],
) -> None:
    if not access:
        return
    if len(tool_traces) <= previous_trace_count:
        return
    trace = tool_traces[-1]
    if not isinstance(trace, dict):
        return
    trace["memory_bucket"] = str(access.get("bucket") or "")
    trace["memory_hit"] = bool(access.get("hit"))


def copy_memory_counters(source: object) -> Tuple[Dict[str, int], Dict[str, int]]:
    if isinstance(source, dict):
        return dict(source.get("memory_hits") or {}), dict(source.get("memory_misses") or {})
    return {}, {}


def update_memory_counters(source: object, access: Dict[str, object]) -> Tuple[Dict[str, int], Dict[str, int]]:
    hits, misses = copy_memory_counters(source)
    bucket = str(access.get("bucket") or "").strip()
    if not bucket:
        return hits, misses
    if bool(access.get("hit")):
        hits[bucket] = int(hits.get(bucket) or 0) + 1
    else:
        misses[bucket] = int(misses.get(bucket) or 0) + 1
    return hits, misses


__all__ = [
    "MemoryAccess",
    "attach_memory_access_to_trace",
    "consume_memory_access",
    "copy_memory_counters",
    "set_memory_access",
    "update_memory_counters",
]
