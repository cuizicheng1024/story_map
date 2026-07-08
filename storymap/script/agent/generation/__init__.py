"""
agent.generation — 顶层对外导出 (re-export)
"""

from __future__ import annotations

from ...api.artifact_api import create_artifact_api
from ...api.generation_api import create_generation_api
from ..generation_tools import create_generation_tools


def __getattr__(name: str):
    if name == "create_story_markdown_agent":
        from ...runtime.legacy_agent.graph import create_story_markdown_agent as _impl
        return _impl
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_artifact_api",
    "create_story_markdown_agent",
    "create_generation_api",
    "create_generation_tools",
]
