"""
============================================================================
  agent.generation — 顶层对外导出 (re-export)
============================================================================
  把 agent 子包下的核心 API 集中暴露给上层 (api 层 / 脚本) 使用。
  通过 PEP 562 __getattr__ 懒加载 create_story_markdown_agent，避免循环引用。

----------------------------------------------------------------------------
  一、Tool / Memory Plan
----------------------------------------------------------------------------
  对外暴露 4 个工厂函数：
      create_artifact_api            : 产物 (artifacts/) 读写接口
      create_generation_api          : 人物生成入口接口
      create_generation_tools        : LLM 可调用的工具字典
      create_story_markdown_agent    : 真正的 LLM Agent 编排 (来自 runtime.legacy_agent)

  这些函数不直接写盘，但会被上层调用以触发整条流水线 (LLM → markdown → html)

----------------------------------------------------------------------------
  二、PDCA 循环
----------------------------------------------------------------------------
  Plan  : 调用前确认目标人物名已通过 classify_story_person_authenticity 校验
  Do    : 上层调用 create_story_markdown_agent(client, person) → 内部走 generation_service
  Check : 上层根据 result["ok"] / result["degraded"] 决定是否落库
  Act   : 当新增 re-export 符号时，更新 __all__ 列表与 __getattr__

----------------------------------------------------------------------------
  三、5M1E
----------------------------------------------------------------------------
  Man(人)        : 本文件是纯 re-export 层，不应在 __getattr__ 中实现业务逻辑
  Machine(机)   : 任意 Python 3.10+
  Material(料)  : 无 IO
  Method(法)    : re-export + 懒加载
  Measurement(测): 无独立指标
  Environment(环): import 顺序敏感 — agent 子包必须先于 api 子包装载
============================================================================
"""

from __future__ import annotations

from ..api.artifact_api import create_artifact_api
from ..api.generation_api import create_generation_api
from .generation_tools import create_generation_tools


def __getattr__(name: str):
    # create_story_markdown_agent 来自 runtime.legacy_agent.graph，懒加载避免循环 import
    if name == "create_story_markdown_agent":
        from ..runtime.legacy_agent.graph import create_story_markdown_agent as _impl
        return _impl
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_artifact_api",
    "create_story_markdown_agent",
    "create_generation_api",
    "create_generation_tools",
]
