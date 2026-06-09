from __future__ import annotations

try:
    from ..story_generation_api import GenerationState
    from ..story_tooling import ToolSpec, tool
except ImportError:
    from story_generation_api import GenerationState
    from story_tooling import ToolSpec, tool

__all__ = ["GenerationState", "ToolSpec", "tool"]
