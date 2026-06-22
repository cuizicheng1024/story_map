from __future__ import annotations

from ..cli.tooling import ToolSpec, tool


def __getattr__(name: str):
    # GenerationState 在 api.generation_api 定义，懒加载以避免循环 import
    if name == "GenerationState":
        from ..api.generation_api import GenerationState as _GS
        return _GS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["GenerationState", "ToolSpec", "tool"]
