from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """单个管线步骤的执行结果。"""
    name: str
    label: str
    status: str  # ok / failed / skipped / warning
    message: str = ""
    duration: float = 0.0


@dataclass
class PipelineReport:
    """管线最终汇总报告。"""
    results: list[StepResult] = field(default_factory=list)
    total_steps: int = 0
    ok_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    hard_failures: list[str] = field(default_factory=list)

    def add(self, r: StepResult) -> None:
        self.results.append(r)
        self.total_steps += 1
        if r.status == "ok":
            self.ok_steps += 1
        elif r.status == "failed":
            self.failed_steps += 1
        elif r.status == "skipped":
            self.skipped_steps += 1

    def print_summary(self) -> None:
        bar = "═" * 60
        print(f"\n{bar}", flush=True)
        print("  管线执行汇总", flush=True)
        print(bar, flush=True)
        status_icon = {"ok": "✓", "failed": "✗", "skipped": "○", "warning": "⚠"}
        for r in self.results:
            icon = status_icon.get(r.status, "?")
            dur = f" ({r.duration:.1f}s)" if r.duration > 0 else ""
            msg = f" — {r.message}" if r.message else ""
            print(f"  {icon} {r.name} [{r.status}]{dur}{msg}", flush=True)
        print(f"\n  总计: {self.total_steps} 步 | ✓{self.ok_steps} ✗{self.failed_steps} ○{self.skipped_steps}", flush=True)
        if self.hard_failures:
            print(f"  ⛔ 硬失败: {', '.join(self.hard_failures)}", flush=True)
        print(bar, flush=True)
