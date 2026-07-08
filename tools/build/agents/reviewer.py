"""审阅 Agent — 修复后二次审计 + 前后对比 + 记忆写入。

职责：
  1. 接收编辑 Agent 修复后的 HTML 目录
  2. 重新执行全量审计（调用 Searcher）
  3. 生成前后对比报告
  4. 将审计结果写入 project_memory.md
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.build.agents.base import AgentReport, BaseAgent


class ReviewerAgent(BaseAgent):
    """审阅 Agent — 修复后校验 + 对比 + 记忆写入。"""

    name = "reviewer"
    label = "审阅 Agent"
    description = "修复后二次审计、生成前后对比、自动写入项目记忆"

    def __init__(
        self,
        html_dir: Path | None = None,
        report_path: Path | None = None,
        memory_path: Path | None = None,
        verbose: bool = True,
    ):
        super().__init__(verbose=verbose)
        repo_root = Path(__file__).resolve().parents[3]
        self.html_dir = html_dir or (repo_root / "artifacts" / "story_map")
        self.report_path = report_path or (repo_root / "tools" / "debug" / "knowledge_audit_v2.json")
        self.memory_path = memory_path or (
            Path.home() / ".trae-cn" / "memory" / "projects"
            / "-Users-bytedance-Desktop-storymap" / "project_memory.md"
        )
        self._before_report: dict | None = None
        self._after_report: dict | None = None

    # ── 运行 Searcher ──

    def _run_searcher(self) -> dict:
        """调用搜索 Agent 执行审计。"""
        from tools.build.agents.searcher import SearcherAgent

        searcher = SearcherAgent(
            html_dir=self.html_dir,
            report_path=self.report_path,
            verbose=False,  # 审阅 Agent 自己控制日志
        )
        searcher_report = searcher.run()
        if searcher_report.is_failed():
            raise RuntimeError(f"搜索 Agent 失败: {searcher_report.message}")

        return self._safe_read_json(self.report_path) or {}

    # ── 对比生成 ──

    def _generate_diff(self) -> dict[str, Any]:
        """生成修复前后对比。"""
        before_errors = self._before_report.get("errors", {}) if self._before_report else {}
        after_errors = self._after_report.get("errors", {}) if self._after_report else {}

        before_files = set(before_errors.keys())
        after_files = set(after_errors.keys())

        resolved = before_files - after_files
        new_issues = after_files - before_files
        persistent = before_files & after_files

        before_stats = self._before_report.get("stats", {}) if self._before_report else {}
        after_stats = self._after_report.get("stats", {}) if self._after_report else {}

        stat_diffs = {}
        for key in set(list(before_stats.keys()) + list(after_stats.keys())):
            b = before_stats.get(key, 0)
            a = after_stats.get(key, 0)
            stat_diffs[key] = {"before": b, "after": a, "delta": b - a}

        return {
            "resolved": sorted(resolved),
            "new_issues": sorted(new_issues),
            "persistent": sorted(persistent),
            "stat_diffs": stat_diffs,
            "before_total_issues": self._before_report.get("files_with_issues", 0) if self._before_report else 0,
            "after_total_issues": self._after_report.get("files_with_issues", 0) if self._after_report else 0,
        }

    # ── 记忆写入 ──

    def _write_memory(self, diff: dict) -> bool:
        """将审计结果写入 project_memory.md。"""
        if not self.memory_path.exists():
            self._log(f"记忆文件不存在: {self.memory_path}", "warn")
            return False

        after = self._after_report or {}
        total = after.get("total_files", 0)
        issues = after.get("files_with_issues", 0)
        stats = after.get("stats", {})
        error_files = after.get("errors", {})

        clean_rate = round((total - issues) / total * 100, 1) if total > 0 else 100.0

        category_lines = []
        for key, label in [
            ("think_leak", "LLM 思考泄露"),
            ("chapter", "章节编号错误"),
            ("short_review", "short_review 空值"),
            ("markdown", "Markdown 占位符"),
            ("coord", "坐标缺失"),
            ("relation", "近现代关系措辞"),
        ]:
            count = stats.get(key, 0)
            icon = "✓" if count == 0 else "✗"
            category_lines.append(f"  - [{icon}] {label}: {count}")

        error_file_lines = []
        if error_files:
            for name in sorted(error_files.keys()):
                errs = error_files[name]
                err_types: set[str] = set()
                for e in errs:
                    if "LLM" in e or "think" in e.lower():
                        err_types.add("think_leak")
                    elif "章节" in e:
                        err_types.add("chapter")
                    elif "坐标" in e:
                        err_types.add("coord")
                    elif "short_review" in e:
                        err_types.add("short_review")
                    elif "占位符" in e or "暂无" in e or "待补充" in e:
                        err_types.add("markdown")
                    else:
                        err_types.add("other")
                error_file_lines.append(f"  - {name}: {', '.join(sorted(err_types))}")
        else:
            error_file_lines.append("  (无)")

        resolved_info = ""
        if diff["resolved"]:
            resolved_info = f"\n- 本次修复: {len(diff['resolved'])} 个文件 ({', '.join(diff['resolved'][:10])})"

        section_marker = "## 知识审计状态"
        section_content = f"""
{section_marker}
- 审计时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 总文件数: {total}
- 问题文件: {issues}
- 健康率: {clean_rate}%{resolved_info}
- 分类统计:
{chr(10).join(category_lines)}
- 问题文件明细:
{chr(10).join(error_file_lines)}
"""

        memory_text = self.memory_path.read_text(encoding="utf-8")

        import re as _re
        if section_marker in memory_text:
            pattern = _re.compile(
                rf"^{_re.escape(section_marker)}.*?(?=^## |\Z)",
                _re.MULTILINE | _re.DOTALL,
            )
            memory_text = pattern.sub(section_content.strip(), memory_text)
        else:
            memory_text = memory_text.rstrip() + "\n\n" + section_content.strip() + "\n"

        self._safe_write(self.memory_path, memory_text)
        self._log("审计结果已写入 project_memory.md", "ok")
        return True

    # ── 主执行 ──

    def _execute(self, **kwargs) -> AgentReport:
        # 加载修复前报告（如果提供了）
        before_path = kwargs.get("before_report_path")
        if before_path:
            self._before_report = self._safe_read_json(Path(before_path))
        elif self.report_path.exists():
            # 用当前报告作为"修复前"
            self._before_report = self._safe_read_json(self.report_path)

        if self._before_report:
            bf = self._before_report.get("files_with_issues", "?")
            self._log(f"修复前基线: {bf} 个问题文件")

        # 执行二次审计
        self._log("执行二次全量审计...")
        self._after_report = self._run_searcher()

        after_issues = self._after_report.get("files_with_issues", 0)
        after_total = self._after_report.get("total_files", 0)
        self._log(f"审计完成: {after_issues}/{after_total} 文件有问题")

        # 生成对比
        diff = self._generate_diff()
        self._log(f"对比: 修复 {len(diff['resolved'])} 个, 残留 {len(diff['persistent'])} 个, 新增 {len(diff['new_issues'])} 个")

        # 写入记忆
        memory_ok = self._write_memory(diff)

        # 质量评分与准入门禁
        blocking_issues = after_issues
        quality_score = max(0, 100 - min(blocking_issues * 8, 80) - min(len(diff["new_issues"]) * 5, 20))
        gate = {
            "passed": blocking_issues == 0,
            "quality_score": quality_score,
            "blocking_issues": blocking_issues,
            "new_issues": len(diff["new_issues"]),
            "policy": {"block_on_any_after_issue": True, "min_score": 75},
        }

        # 判定状态
        if after_issues == 0:
            status = "ok"
            msg = "全部通过！零问题。"
        elif diff["persistent"]:
            status = "ok"
            msg = f"残留 {len(diff['persistent'])} 个文件，需人工处理"
        else:
            status = "ok"
            msg = f"{after_issues} 个文件有问题"

        return AgentReport(
            agent_name=self.name,
            status=status,
            message=msg,
            details={
                "after_issues": after_issues,
                "after_total": after_total,
                "quality_score": quality_score,
                "gate": gate,
                "diff": diff,
                "memory_written": memory_ok,
            },
        )


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="审阅 Agent — 二次审计 + 记忆写入")
    ap.add_argument("--dir", type=Path, default=None, help="HTML 目录")
    args = ap.parse_args()
    agent = ReviewerAgent(html_dir=args.dir, verbose=True)
    report = agent.run()
    print(f"\n{report.message}")
