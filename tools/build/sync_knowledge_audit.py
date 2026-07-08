#!/usr/bin/env python3
"""知识审计与自动修复 — 薄包装（已废弃）。

⚠️ 已迁移至 tools/build/agents/ 下的五 Agent 管线。
   本模块保留向后兼容的公开 API，内部委托给新 Agent 实现。
   请改用 Agent CLI 或 AssemblerAgent：

     python3 tools/build/agents/assembler.py --dir artifacts/story_map

用法（向后兼容）:
  from tools.build.sync_knowledge_audit import audit, fix_all, audit_and_fix, sync_knowledge_audit
  report = audit()                          # 搜索 Agent 审计
  log = fix_all()                           # 编辑 Agent 修复
  report, log = audit_and_fix()             # 搜索 + 编辑
  sync_knowledge_audit()                    # 完整管线
"""

from __future__ import annotations

import warnings
from pathlib import Path

warnings.warn(
    "tools.build.sync_knowledge_audit is deprecated. "
    "Use tools.build.agents.assembler.AssemblerAgent instead.",
    DeprecationWarning,
    stacklevel=2,
)

from tools.build.agents.searcher import SearcherAgent
from tools.build.agents.editor import EditorAgent
from tools.build.agents.reviewer import ReviewerAgent


def audit(target_dir: Path | None = None, save_report: bool = True) -> dict:
    """全量审计（委托给搜索 Agent）。"""
    agent = SearcherAgent(html_dir=target_dir, verbose=False)
    report = agent.run()
    if report.is_failed():
        return {"errors": {}, "stats": {}, "files_with_issues": 0, "total_files": 0}
    return agent._safe_read_json(agent.report_path) or {}


def fix_all(target_dir: Path | None = None) -> list[str]:
    """自动修复（委托给编辑 Agent）。"""
    agent = EditorAgent(html_dir=target_dir, verbose=False)
    report = agent.run()
    return report.details.get("fix_logs", [])


def audit_and_fix(target_dir: Path | None = None) -> tuple[dict, list[str]]:
    """先审计后修复（委托给搜索 + 编辑 Agent）。"""
    audit_report = audit(target_dir=target_dir, save_report=True)
    if not audit_report.get("errors"):
        return audit_report, []
    fix_logs = fix_all(target_dir=target_dir)
    return audit_report, fix_logs


def append_audit_to_memory(report: dict | None = None) -> bool:
    """审计结果写入项目记忆（委托给审阅 Agent）。"""
    reviewer = ReviewerAgent(verbose=False)
    reviewer._after_report = report or audit(save_report=True)
    diff = reviewer._generate_diff()
    return reviewer._write_memory(diff)


def sync_knowledge_audit(target_dir: Path | None = None) -> Path:
    """完整知识审计管线（搜索 → 编辑 → 审阅）。"""
    agent = ReviewerAgent(html_dir=target_dir, verbose=True)
    report = agent.run()
    return agent.report_path
