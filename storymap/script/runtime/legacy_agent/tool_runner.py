"""工具调用器模块 — 带重试和熔断保护的工具调用封装。

本模块是管线 A 的"安全执行层"，为每个 Agent 的工具调用提供统一的防护机制：

  1. 熔断检查（Circuit Breaker）：工具连续失败 3 次 → 熔断 60 秒
  2. LLM 预算控制：超过 llm_calls_limit → 拒绝调用
  3. 指数退避重试：瞬时故障自动重试（1s → 2s → 4s），最多 2 次
  4. 统一错误封装：所有异常包装为 ToolCallError，携带完整上下文

调用方式：
    from .tool_runner import call_tool, ToolCallError

    try:
        result = call_tool(state, my_tool, payload, agent_step="search_agent")
    except ToolCallError as exc:
        # 工具调用失败，exc 中包含 tool_traces 和 llm_calls_used
        # 上层 Agent 节点应该降级为 fallback 结果

重试策略：
  可重试的错误类型（瞬时性故障）：
    - ConnectionError, Timeout, RemoteDisconnected
    - ReadTimeout, ConnectTimeout
    - HTTPError（5xx 类服务端错误）
    - ServiceUnavailable, TooManyRequests（429 限流）
    - InternalServerError

  不可重试的错误类型（业务逻辑错误）：
    - LLM_CALL_BUDGET_EXCEEDED（预算耗尽）
    - ValueError, TypeError 等（参数错误）
    - 4xx 类客户端错误（非 429）

熔断器参数：
  - failure_threshold: 连续失败 3 次后熔断
  - reset_timeout:     熔断后 60 秒自动恢复
  - half_open_max:     半开状态最多 1 次探测调用
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, TypedDict

from ...cli.tooling import invoke_tool                     # 底层工具调用（来自 CLI 模块）
from .circuit_breaker import get_circuit_breaker           # 熔断器
from .state import StoryAgentState
from .telemetry import (
    attach_memory_access_to_trace,  # 将记忆访问信息附加到工具追踪
    consume_memory_access,          # 消费并重置记忆访问状态
)

# ── 可重试的错误类型 ──
# 这些是瞬时性故障，适合指数退避重试
_RETRYABLE_ERRORS = (
    "ConnectionError",
    "Timeout",
    "RemoteDisconnected",
    "ReadTimeout",
    "ConnectTimeout",
    "HTTPError",         # 5xx 类服务端错误
    "ServiceUnavailable",
    "TooManyRequests",   # 429 限流
    "InternalServerError",
)


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否适合重试（瞬时性故障而非业务逻辑错误）。

    检查异常类型名称和异常消息中的关键词。

    Args:
        exc: 异常实例

    Returns:
        bool: True 表示适合重试
    """
    exc_type = type(exc).__name__
    if exc_type in _RETRYABLE_ERRORS:
        return True
    message = str(exc).lower()
    retryable_keywords = ("429", "500", "502", "503", "504", "timeout", "connection reset", "too many requests")
    return any(kw in message for kw in retryable_keywords)


# ═══════════════════════════════════════════════════════════════════
#  类型定义
# ═══════════════════════════════════════════════════════════════════

class ToolCallError(RuntimeError):
    """工具调用异常 — 携带完整上下文的统一错误类型。

    上层 Agent 节点捕获此异常后，可以：
      1. 读取 tool_traces 追加到状态中
      2. 读取 llm_calls_used 更新预算计数器
      3. 记录 degraded_reasons
      4. 降级为 fallback 结果

    Attributes:
        tool_traces:   本次调用产生的所有工具追踪记录
        llm_calls_used: 累计 LLM 调用次数
        original:      原始异常（如果有）
    """

    def __init__(
        self,
        message: str,
        *,
        tool_traces: List[Dict[str, object]],
        llm_calls_used: int,
        original: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.tool_traces = list(tool_traces or [])
        self.llm_calls_used = int(llm_calls_used)
        self.original = original


class ToolRunResult(TypedDict):
    """工具调用成功时的返回结构。

    Fields:
        result:        工具函数的返回值（类型取决于具体工具）
        tool_traces:   工具调用追踪记录列表
        llm_calls_used: 累计 LLM 调用次数
        memory_access:  记忆访问信息（命中/未命中）
    """
    result: object
    tool_traces: List[Dict[str, object]]
    llm_calls_used: int
    memory_access: Dict[str, object]


# ═══════════════════════════════════════════════════════════════════
#  工具元数据提取
# ═══════════════════════════════════════════════════════════════════

def _tool_meta(func: Callable[..., object]) -> object:
    """提取工具函数的 __tool__ 元数据对象。

    管线 A 的工具函数通过 @tool 装饰器注册，装饰器会在函数上设置
    __tool__ 属性，包含 name、tags 等元信息。

    Args:
        func: 工具函数

    Returns:
        object: __tool__ 元数据对象，不存在时返回 None
    """
    return getattr(func, "__tool__", None)


def _tool_tags(func: Callable[..., object]) -> set[str]:
    """提取工具函数的标签集合。

    标签用于标识工具类型：
      - "llm": 该工具会调用 LLM，需要计入预算
      - "llm_optional": 该工具可能调用 LLM

    Args:
        func: 工具函数

    Returns:
        set[str]: 标签集合
    """
    meta = _tool_meta(func)
    raw = getattr(meta, "tags", ()) if meta is not None else ()
    return {str(item).strip() for item in raw if str(item).strip()}


def _is_llm_tool(func: Callable[..., object]) -> bool:
    """判断工具是否会调用 LLM。

    只有标记为 "llm" 或 "llm_optional" 的工具才会计入 LLM 预算。

    Args:
        func: 工具函数

    Returns:
        bool: True 表示该工具会调用 LLM
    """
    tags = _tool_tags(func)
    return bool({"llm", "llm_optional"} & tags)


def _tool_name(func: Callable[..., object]) -> str:
    """获取工具名称（用于熔断器注册和日志）。

    Args:
        func: 工具函数

    Returns:
        str: 工具名称
    """
    meta = _tool_meta(func)
    return str(getattr(meta, "name", func.__name__)) if meta is not None else func.__name__


def _check_and_consume_llm_budget(
    state: StoryAgentState,
    func: Callable[..., object],
) -> int:
    """检查并消费 LLM 调用预算。

    如果工具不调用 LLM，直接返回当前计数。
    如果预算已耗尽，抛出 RuntimeError("LLM_CALL_BUDGET_EXCEEDED:...").

    Args:
        state: 共享状态
        func:  工具函数

    Returns:
        int: 更新后的 llm_calls_used（已 +1）

    Raises:
        RuntimeError: 预算已耗尽
    """
    if not _is_llm_tool(func):
        return int(state.get("llm_calls_used") or 0)

    used = int(state.get("llm_calls_used") or 0)
    limit = max(0, int(state.get("llm_calls_limit") or 0))

    if used >= limit:
        raise RuntimeError(f"LLM_CALL_BUDGET_EXCEEDED:{used}/{limit}")

    return used + 1


# ═══════════════════════════════════════════════════════════════════
#  核心函数：带防护的工具调用
# ═══════════════════════════════════════════════════════════════════

def call_tool(
    state: StoryAgentState,
    func: Callable[..., object],
    payload: object,
    *,
    agent_step: str = "",
    max_retries: int = 2,
    base_delay: float = 1.0,
    **extra_kwargs: object,
) -> ToolRunResult:
    """调用工具，内置熔断检查、预算控制和指数退避重试。

    这是管线 A 所有工具调用的统一入口，提供三层防护：

    1. 熔断检查：工具连续失败 3 次 → 拒绝调用，抛出 ToolCallError("CIRCUIT_OPEN:...")
    2. 预算检查：LLM 调用超过上限 → 抛出 ToolCallError("LLM_CALL_BUDGET_EXCEEDED:...")
    3. 指数退避重试：瞬时故障自动重试（1s → 2s → 4s）

    调用流程：
      ┌─ 熔断检查 ──→ 熔断中？→ 抛出 ToolCallError
      │
      ├─ 预算检查 ──→ 超限？→ 抛出 ToolCallError
      │
      ├─ 执行工具 ──→ 成功？→ 重置熔断器 + 返回结果
      │            └─ 失败？→ 可重试？→ 等待 delay + 重试
      │                     └─ 不可重试？→ 记录失败 + 抛出 ToolCallError
      │
      └─ 记录熔断器状态（成功 → reset / 失败 → failure_count++）

    Args:
        state:       共享状态（用于读取预算和追踪）
        func:        工具函数
        payload:     工具参数（传给 func 的实参）
        agent_step:  调用方 Agent 名称（如 "search_agent"，用于追踪）
        max_retries: 最大重试次数（不含首次调用），默认 2 次
        base_delay:  首次重试等待秒数，后续指数翻倍（1s → 2s → 4s）
        **extra_kwargs: 额外关键字参数，透传给工具函数（如 dynasty="唐"）

    Returns:
        ToolRunResult: {"result": ..., "tool_traces": [...], "llm_calls_used": int, "memory_access": {...}}

    Raises:
        ToolCallError: 工具调用失败（熔断 / 预算耗尽 / 重试耗尽）
    """
    # 每次调用从空列表开始，避免与节点层的 state 累积产生重复
    tool_traces: List[Dict[str, object]] = []
    llm_calls_used = int(state.get("llm_calls_used") or 0)
    previous_trace_count = 0

    # ── 防护 1：熔断检查 ──
    name = _tool_name(func)
    breaker = get_circuit_breaker(name)
    if not breaker.allow():
        raise ToolCallError(
            f"CIRCUIT_OPEN:{name}:连续失败 {breaker.failure_count} 次，熔断至 {breaker.reset_time}",
            tool_traces=tool_traces,
            llm_calls_used=llm_calls_used,
        )

    last_exc: Optional[Exception] = None

    # ── 防护 2+3：预算检查 + 指数退避重试 ──
    for attempt in range(max_retries + 1):  # 首次 + max_retries 次重试
        try:
            # 预算检查
            llm_calls_used = _check_and_consume_llm_budget(state, func)

            # 执行工具
            result = invoke_tool(func, payload, trace_collector=tool_traces, agent_step=agent_step, **extra_kwargs)

            # ── 成功 → 重置熔断器 ──
            breaker.record_success()

            # 处理记忆访问信息
            memory_access = consume_memory_access(func)
            attach_memory_access_to_trace(
                tool_traces,
                previous_trace_count=previous_trace_count,
                access=memory_access,
            )

            return {
                "result": result,
                "tool_traces": tool_traces,
                "llm_calls_used": llm_calls_used,
                "memory_access": memory_access,
            }

        except Exception as exc:
            last_exc = exc

            # 预算耗尽不可重试
            if "LLM_CALL_BUDGET_EXCEEDED" in str(exc):
                break

            # 瞬时故障 + 还有重试次数 → 等待后重试
            if attempt < max_retries and _is_retryable(exc):
                delay = base_delay * (2 ** attempt)  # 指数退避：1s → 2s → 4s
                time.sleep(delay)
                continue

            # 不可重试或重试耗尽 → 退出循环
            break

    # ── 失败 → 记录到熔断器 ──
    consume_memory_access(func)
    if last_exc is not None and "LLM_CALL_BUDGET_EXCEEDED" not in str(last_exc):
        breaker.record_failure()

    # 抛出统一异常
    raise ToolCallError(
        str(last_exc or "unknown error"),
        tool_traces=tool_traces,
        llm_calls_used=llm_calls_used,
        original=last_exc if isinstance(last_exc, Exception) else None,
    ) from last_exc


__all__ = [
    "ToolCallError",
    "ToolRunResult",
    "call_tool",
]
