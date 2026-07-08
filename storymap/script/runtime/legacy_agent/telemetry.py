"""
故事地图 Agent 遥测模块（内存访问追踪）。

本模块提供了内存缓存访问的埋点/遥测基础设施，用于在工具调用链中
追踪和记录内存缓存（memory store）的命中/未命中情况。

核心机制：
- 通过函数对象的动态属性（__memory_last_access__）传递缓存访问状态，
  避免侵入式地修改工具函数的签名
- 支持将内存访问信息附加到工具调用追踪记录中
- 提供命中/未命中计数器，用于汇总统计

使用流程：
1. 在缓存操作前后调用 set_memory_access() 在函数对象上标记访问结果
2. 调用 consume_memory_access() 消费该标记（读取后清除）
3. 使用 attach_memory_access_to_trace() 将标记信息附加到追踪记录
4. 使用 update_memory_counters() 累加命中/未命中计数
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple, TypedDict


# =============================================================================
# 类型定义
# =============================================================================

class MemoryAccess(TypedDict, total=False):
    """
    内存缓存访问记录的结构化类型。

    Attributes:
        bucket: 访问的缓存桶名称（如 "people"、"places"）。
        hit: 是否命中缓存（True=命中，False=未命中）。
    """
    bucket: str
    hit: bool


# =============================================================================
# 内存访问标记的设置与消费
# =============================================================================

def set_memory_access(func: Callable[..., object], *, bucket: str, hit: bool) -> None:
    """
    在函数对象上设置内存缓存访问标记。

    通过动态属性 `__memory_last_access__` 将访问信息临时附加到函数对象上，
    供后续的 consume_memory_access() 或 attach_memory_access_to_trace() 消费。

    Args:
        func: 目标函数对象。
        bucket: 访问的缓存桶名称。
        hit: 是否命中缓存。
    """
    try:
        setattr(func, "__memory_last_access__", {"bucket": str(bucket or "").strip(), "hit": bool(hit)})
    except Exception:
        return


def consume_memory_access(func: Callable[..., object]) -> MemoryAccess:
    """
    消费（读取并清除）函数对象上的内存缓存访问标记。

    读取后立即清除标记，确保同一标记不会被重复消费。

    Args:
        func: 目标函数对象。

    Returns:
        MemoryAccess: 内存访问记录，若标记不存在则返回空字典。
    """
    access = getattr(func, "__memory_last_access__", None)
    # 读取后立即清除，避免重复消费
    try:
        setattr(func, "__memory_last_access__", None)
    except Exception:
        pass
    return dict(access) if isinstance(access, dict) else {}


# =============================================================================
# 内存访问信息附加到工具追踪记录
# =============================================================================

def attach_memory_access_to_trace(
    tool_traces: List[Dict[str, object]],
    *,
    previous_trace_count: int,
    access: Dict[str, object],
) -> None:
    """
    将内存缓存访问信息附加到最新的工具追踪记录中。

    仅当工具追踪列表中有新增的记录时（len(tool_traces) > previous_trace_count），
    才会将访问信息写入最新的那条记录中。

    Args:
        tool_traces: 工具调用追踪记录列表（会被原地修改）。
        previous_trace_count: 之前已知的追踪记录数量，用于判断是否有新记录。
        access: 内存访问信息字典，包含 bucket 和 hit 字段。
    """
    # 无访问信息时跳过
    if not access:
        return

    # 无新增记录时跳过
    if len(tool_traces) <= previous_trace_count:
        return

    # 将信息写入最新的追踪记录
    trace = tool_traces[-1]
    if not isinstance(trace, dict):
        return
    trace["memory_bucket"] = str(access.get("bucket") or "")
    trace["memory_hit"] = bool(access.get("hit"))


# =============================================================================
# 内存缓存命中/未命中计数器
# =============================================================================

def copy_memory_counters(source: object) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    从源对象中复制内存缓存命中/未命中计数器。

    用于在需要累积统计时获取当前的计数器快照。

    Args:
        source: 包含 memory_hits 和 memory_misses 字段的对象（通常是 dict）。

    Returns:
        Tuple[Dict[str, int], Dict[str, int]]: (命中计数, 未命中计数) 的元组，
        每个都是按桶名称索引的计数字典。
    """
    if isinstance(source, dict):
        return dict(source.get("memory_hits") or {}), dict(source.get("memory_misses") or {})
    return {}, {}


def update_memory_counters(source: object, access: Dict[str, object]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    基于一次内存访问记录更新计数器。

    从源对象中复制现有计数器，然后根据本次访问的桶和命中情况递增对应的计数。

    Args:
        source: 包含现有 memory_hits/memory_misses 的对象。
        access: 本次内存访问记录，包含 bucket 和 hit 字段。

    Returns:
        Tuple[Dict[str, int], Dict[str, int]]: 更新后的 (命中计数, 未命中计数) 元组。
    """
    # 复制现有计数器
    hits, misses = copy_memory_counters(source)

    # 桶名无效时直接返回原计数器
    bucket = str(access.get("bucket") or "").strip()
    if not bucket:
        return hits, misses

    # 根据命中情况递增对应计数器
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
