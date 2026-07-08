"""熔断器模块 — 工具级熔断保护。

本模块为管线 A 的每个工具提供独立的熔断器（Circuit Breaker），
防止级联故障：一个工具持续失败时，不再重复调用它，而是快速失败。

熔断器状态机：

  CLOSED（正常）──连续失败 threshold 次──→ OPEN（熔断）
                                                  │
                                          reset_timeout 秒后
                                                  │
                                                  ▼
  CLOSED（正常）←──成功── HALF_OPEN（探测）←── 半开尝试

参数（可配置）：
  - failure_threshold: 连续失败多少次后熔断（默认 3）
  - reset_timeout:     熔断后多少秒自动进入半开状态（默认 60）
  - half_open_max:     半开状态下最多允许多少次探测调用（默认 1）

隔离性：
  - 每个工具名对应一个独立的熔断器
  - search_person_info 挂了不影响 generate_markdown
  - 熔断器是全局单例（模块级 dict）

使用方式：
    from .circuit_breaker import get_circuit_breaker

    breaker = get_circuit_breaker("search_person_info")
    if not breaker.allow():
        raise ToolCallError("CIRCUIT_OPEN")
    try:
        result = do_search()
        breaker.record_success()
    except Exception:
        breaker.record_failure()
"""

from __future__ import annotations

import time
from typing import Dict


class CircuitBreaker:
    """工具级熔断器。

    状态转换：
      CLOSED  → 连续失败 failure_threshold 次 → OPEN
      OPEN    → reset_timeout 秒后 → HALF_OPEN
      HALF_OPEN → 成功 → CLOSED（重置计数器）
      HALF_OPEN → 失败 → OPEN（重新计时）

    Attributes:
        name:              工具名称（用于日志和调试）
        failure_count:     当前连续失败次数
        failure_threshold: 触发熔断的连续失败阈值
        state:             当前状态（"closed" / "open" / "half_open"）
        last_failure_time: 最后一次失败的时间戳
        opened_at:         进入 OPEN 状态的时间戳
        reset_timeout:     熔断恢复时间（秒）
        half_open_attempts: 半开状态已尝试次数
        half_open_max:     半开状态最大尝试次数
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        half_open_max: int = 1,
    ) -> None:
        self.name = name
        self.failure_count = 0
        self.failure_threshold = max(1, int(failure_threshold))
        self.state: str = "closed"
        self.last_failure_time: float = 0.0
        self.opened_at: float = 0.0
        self.reset_timeout = max(0.0, float(reset_timeout))
        self.half_open_attempts = 0
        self.half_open_max = max(1, int(half_open_max))

    def allow(self) -> bool:
        """检查是否允许调用。

        - CLOSED: 允许
        - OPEN 且未超时: 拒绝
        - OPEN 且已超时: 转为 HALF_OPEN，允许
        - HALF_OPEN 且未超探测次数: 允许
        - HALF_OPEN 且已超探测次数: 拒绝

        Returns:
            bool: True 表示允许调用
        """
        now = time.time()

        if self.state == "closed":
            return True

        if self.state == "open":
            elapsed = now - self.opened_at
            if elapsed >= self.reset_timeout:
                # 超时 → 进入半开状态探测
                self.state = "half_open"
                self.half_open_attempts = 0
                return True
            return False

        if self.state == "half_open":
            # 半开状态下限制探测次数
            return self.half_open_attempts < self.half_open_max

        return True

    def record_success(self) -> None:
        """记录一次成功调用。

        - CLOSED: 重置 failure_count
        - HALF_OPEN: 转为 CLOSED，重置所有计数器
        """
        if self.state == "half_open":
            self.state = "closed"
            self.failure_count = 0
            self.half_open_attempts = 0
        elif self.state == "closed":
            self.failure_count = 0

    def record_failure(self) -> None:
        """记录一次失败调用。

        - CLOSED: failure_count++，达到阈值 → OPEN
        - HALF_OPEN: 直接回到 OPEN
        """
        now = time.time()
        self.last_failure_time = now

        if self.state == "closed":
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                # 达到阈值 → 熔断
                self.state = "open"
                self.opened_at = now
        elif self.state == "half_open":
            # 探测失败 → 回到熔断
            self.state = "open"
            self.opened_at = now
            self.half_open_attempts = 0

    def record_attempt(self) -> None:
        """记录一次半开探测尝试（用于 allow() 外部手动管理计数）。"""
        if self.state == "half_open":
            self.half_open_attempts += 1

    @property
    def reset_time(self) -> str:
        """熔断恢复的剩余时间（人类可读）。"""
        if self.state != "open":
            return "已恢复"
        remaining = max(0.0, self.reset_timeout - (time.time() - self.opened_at))
        return f"{remaining:.0f}秒"


# ═══════════════════════════════════════════════════════════════════
#  全局熔断器注册表（模块级单例）
# ═══════════════════════════════════════════════════════════════════

_CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取或创建指定工具的熔断器。

    首次调用时创建新实例，后续调用返回同一个实例。
    每个工具名对应一个独立的熔断器，互不干扰。

    Args:
        name: 工具名称（如 "search_person_info", "generate_markdown"）

    Returns:
        CircuitBreaker: 该工具的熔断器实例
    """
    if name not in _CIRCUIT_BREAKERS:
        _CIRCUIT_BREAKERS[name] = CircuitBreaker(name)
    return _CIRCUIT_BREAKERS[name]


def reset_all_circuit_breakers() -> None:
    """重置所有熔断器（用于测试和手动恢复）。

    将所有熔断器重置为 CLOSED 状态，清空失败计数。
    """
    _CIRCUIT_BREAKERS.clear()


__all__ = [
    "CircuitBreaker",
    "get_circuit_breaker",
    "reset_all_circuit_breakers",
]
