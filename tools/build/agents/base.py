"""Agent 基类 — 提供日志、重试、异常边界、状态上报等通用能力。

每个独立 Agent 继承此类，只需实现 run() 方法即可获得：
  - 结构化日志
  - 自动异常捕获与状态上报
  - 重试机制
  - 输入/输出校验
  - 耗时统计
"""

from __future__ import annotations

import json
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class AgentReport:
    """Agent 执行结果报告。"""
    agent_name: str
    status: str  # ok / failed / skipped
    message: str = ""
    duration: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_ok(self) -> bool:
        return self.status == "ok"

    def is_failed(self) -> bool:
        return self.status == "failed"


class BaseAgent(ABC):
    """所有 Agent 的抽象基类。"""

    # ── 子类覆盖 ──
    name: str = "base"
    label: str = "Base Agent"
    description: str = ""
    max_retries: int = 1  # 默认不重试
    retry_delay: float = 1.0  # 秒

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._start_time: float = 0.0
        self._log_lines: list[str] = []

    # ── 日志 ──

    def _log(self, msg: str, level: str = "info") -> None:
        prefix = {"info": " ·", "ok": " ✓", "warn": " ⚠", "error": " ✗", "start": " ▶"}.get(level, " ·")
        line = f"[{self.name}] {prefix} {msg}"
        self._log_lines.append(line)
        if self.verbose:
            print(line, flush=True)

    # ── 重试 ──

    def _retry(self, fn: Callable[[], Any], desc: str = "") -> Any:
        """带重试的执行包装器。"""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    self._log(f"{desc} 第 {attempt + 1} 次尝试...", "warn")
                    time.sleep(self.retry_delay)
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    self._log(f"{desc} 失败 ({exc})，准备重试", "warn")
        raise last_exc  # type: ignore[misc]

    # ── 文件 I/O 安全边界 ──

    @staticmethod
    def _safe_read(path: Path) -> str | None:
        """安全读取文本文件，失败返回 None。"""
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except PermissionError as e:
            raise e
        except Exception as e:
            raise IOError(f"读取失败 {path}: {e}") from e

    @staticmethod
    def _safe_write(path: Path, content: str) -> None:
        """安全写入文本文件，自动创建父目录。"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except PermissionError as e:
            raise e
        except Exception as e:
            raise IOError(f"写入失败 {path}: {e}") from e

    @staticmethod
    def _safe_read_json(path: Path) -> dict | None:
        """安全读取 JSON 文件，失败返回 None。"""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        except Exception as e:
            raise IOError(f"JSON 解析失败 {path}: {e}") from e

    @staticmethod
    def _safe_write_json(path: Path, data: Any) -> None:
        """安全写入 JSON 文件。"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            raise IOError(f"JSON 写入失败 {path}: {e}") from e

    # ── 生命周期 ──

    def _pre_run(self) -> None:
        """运行前钩子，子类可覆盖做输入校验。"""
        self._start_time = time.time()
        self._log_lines.clear()
        self._log(f"{self.label} 启动", "start")

    def _post_run(self, report: AgentReport) -> AgentReport:
        """运行后钩子，自动填充耗时。"""
        report.duration = round(time.time() - self._start_time, 2)
        icon = "✓" if report.is_ok() else "✗"
        self._log(f"{self.label} {icon} ({report.duration:.1f}s)", "ok" if report.is_ok() else "error")
        return report

    def _on_error(self, exc: Exception) -> AgentReport:
        """异常处理钩子，生成失败报告。"""
        tb = traceback.format_exc()
        self._log(f"异常: {exc}", "error")
        self._log(tb.split("\n")[-2] if "\n" in tb else tb, "error")
        return AgentReport(
            agent_name=self.name,
            status="failed",
            message=str(exc)[:200],
            duration=round(time.time() - self._start_time, 2),
            errors=[str(exc)],
        )

    # ── 主入口 ──

    def run(self, **kwargs: Any) -> AgentReport:
        """执行 Agent 主逻辑。子类不应覆盖此方法，应覆盖 _execute()。"""
        try:
            self._pre_run()
            report = self._execute(**kwargs)
            return self._post_run(report)
        except Exception as exc:
            return self._on_error(exc)

    @abstractmethod
    def _execute(self, **kwargs: Any) -> AgentReport:
        """子类实现核心逻辑。"""
        ...
