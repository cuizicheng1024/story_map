"""storymap.script.agent 子包：故事生成、生成编排与离线评估实现。"""

from __future__ import annotations

from importlib import import_module

from ..cli.tooling import ToolSpec, tool


_LAZY_EXPORTS = {
    "create_artifact_api": ("storymap.script.agent.generation", "create_artifact_api"),
    "create_story_markdown_agent": ("storymap.script.agent.generation", "create_story_markdown_agent"),
    "create_generation_api": ("storymap.script.agent.generation", "create_generation_api"),
    "create_generation_tools": ("storymap.script.agent.generation", "create_generation_tools"),
    "create_geocode_api": ("storymap.script.agent.knowledge", "create_geocode_api"),
    "create_profile_api": ("storymap.script.agent.knowledge", "create_profile_api"),
    "create_profile_api_from_geocode_api": (
        "storymap.script.agent.knowledge",
        "create_profile_api_from_geocode_api",
    ),
    "create_runtime_api": ("storymap.script.agent.runtime", "create_runtime_api"),
    "create_runtime_helpers": ("storymap.script.agent.runtime", "create_runtime_helpers"),
    "run_main": ("storymap.script.agent.runtime", "run_main"),
    "run_server": ("storymap.script.agent.runtime", "run_server"),
    "GenerationState": ("storymap.script.api.generation_api", "GenerationState"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)


__all__ = [
    "GenerationState",
    "ToolSpec",
    "tool",
    "create_artifact_api",
    "create_story_markdown_agent",
    "create_generation_api",
    "create_generation_tools",
    "create_geocode_api",
    "create_profile_api",
    "create_profile_api_from_geocode_api",
    "create_runtime_api",
    "create_runtime_helpers",
    "run_main",
    "run_server",
]
