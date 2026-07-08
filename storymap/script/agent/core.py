"""
============================================================================
  agent.core — Agent 入口与公共符号门面
============================================================================
  本模块是 "输入人物姓名 → 检索资料 → 生成 HTML" 整条 Agent 流水线的轻量门面。

  GenerationState 由 agent 包的 __init__.py 统一懒加载，本模块只负责导出
  ToolSpec / tool 两个无循环依赖的符号，避免与 api.generation_api 形成循环引用。
============================================================================
"""

from __future__ import annotations

from ..cli.tooling import ToolSpec, tool

__all__ = ["ToolSpec", "tool"]
