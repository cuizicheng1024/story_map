"""管线 A 入口模块 — 人物传记生成 Agent 系统的对外 API。

本模块是管线 A（人物传记生成主链路）的唯一对外入口，提供两个核心函数：

  1. create_agent_tools()  — 创建工具集（可替换默认实现）
  2. create_story_markdown_agent()  — 创建完整的 Agent 系统（含 LangGraph 图 + Runner）

管线 A 的六 Agent 协作流：
  Supervisor → SearchAgent → GeocodeAgent → EditorAgent → CriticAgent → DeliverAgent
                 ↑_____________________________________↓  (修订循环，最多 N 轮)

调用方式：
    from storymap.script.runtime.legacy_agent.graph import generate_markdown_with_agents

    result = generate_markdown_with_agents(llm, "苏轼")
    markdown_text = result["markdown"]
    full_state = result["state"]

依赖关系：
  graph.py ──→ runners.py ──→ nodes.py ──→ router.py / tool_runner.py / fallbacks.py
                                         └── critic_integration.py / geo_integration.py
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

# ── 跨包依赖：人物真实性校验 ──
from ...core.project_paths import classify_story_person_authenticity

# ── 子模块导入 ──
from . import default_tools as _default_tools      # 默认工具实现（search / geocode / generate / validate）
from . import runners as _runners                   # LangGraph 图构建 + 双 Runner（LangGraph / Manual）
from .common import _geocode_api_utils, _geocode_service_utils  # 地理编码工具引用
from .default_tools import (
    _infer_dynasty,                      # 朝代推断工具
    default_fetch_ancient_place_map,     # 默认古地名→现代坐标 映射
    default_generate_markdown,           # 默认 Markdown 生成
    default_queue_hard_place_review,     # 默认困难地名审核队列
    default_search_person_info,          # 默认人物资料检索
)
from .memory import StoryAgentMemoryStore  # 记忆存储（缓存已检索人物资料）
from .nodes import _extract_places_for_mapping  # 从状态中提取待地理编码的地名列表
from .runners import generate_markdown_with_agents  # 便捷入口：一键生成人物 Markdown
from .tools import list_agent_tools  # 列出所有工具及其 schema
from .validation_rules import _extract_year, _lifespan_issues, default_validate_markdown

# ── LangGraph 可用性检测 ──
# 当 langgraph 包未安装时降级为 Manual Runner（顺序执行）
_LANGGRAPH_AVAILABLE = _runners._LANGGRAPH_AVAILABLE
StateGraph = _runners.StateGraph


def _sync_runtime_overrides() -> None:
    """同步运行时覆盖：将外部注入的地理编码工具引用同步到 default_tools 和 runners 模块。

    这是一个模块级闭包技巧，用于在 import 时尚未确定的依赖（如 geocode_service）
    通过 graph.py 统一注入到各个子模块中，避免循环导入。
    """
    _default_tools._geocode_service_utils = _geocode_service_utils
    _default_tools._geocode_api_utils = _geocode_api_utils
    _runners._LANGGRAPH_AVAILABLE = _LANGGRAPH_AVAILABLE
    _runners.StateGraph = StateGraph
    _runners.classify_story_person_authenticity = classify_story_person_authenticity


def create_agent_tools(
    *,
    llm: object = None,
    search_person_info_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    fetch_ancient_place_map_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    queue_hard_place_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
    generate_markdown_fn: Optional[Callable[[Dict[str, object]], str]] = None,
    validate_markdown_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    memory_store: Optional[StoryAgentMemoryStore] = None,
) -> Dict[str, Callable[..., object]]:
    """创建 Agent 工具集，支持注入自定义实现。

    每个参数都可以传入自定义函数来替换默认行为：
      - search_person_info_fn:   检索人物资料（替代默认的 LLM 检索）
      - fetch_ancient_place_map_fn: 古地名→现代坐标映射（替代高德 API）
      - generate_markdown_fn:    生成结构化 Markdown（替代默认 LLM 生成）
      - validate_markdown_fn:    校验 Markdown 质量（替代默认校验规则）
      - memory_store:            记忆存储后端（替代默认内存缓存）

    Returns:
        Dict[str, Callable]: 工具名 → 工具函数的映射字典
    """
    _sync_runtime_overrides()
    return _runners.create_agent_tools(
        llm=llm,
        search_person_info_fn=search_person_info_fn,
        fetch_ancient_place_map_fn=fetch_ancient_place_map_fn,
        queue_hard_place_review_fn=queue_hard_place_review_fn,
        generate_markdown_fn=generate_markdown_fn,
        validate_markdown_fn=validate_markdown_fn,
        memory_store=memory_store,
    )


def create_story_markdown_agent(
    *,
    llm: object = None,
    search_person_info_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    fetch_ancient_place_map_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    queue_hard_place_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
    generate_markdown_fn: Optional[Callable[[Dict[str, object]], str]] = None,
    validate_markdown_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    max_llm_calls: Optional[int] = None,
    memory_store: Optional[StoryAgentMemoryStore] = None,
    render_pipeline: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """创建完整的管线 A Agent 系统。

    这是对外的主要工厂函数，返回一个包含以下字段的字典：
      - tools:        工具集字典（工具名 → 函数）
      - tool_specs:   工具 schema 列表（用于 LLM function calling）
      - run:          Agent 执行函数 callable(person, max_revisions, llm_calls_limit) → result
      - langgraph_available: LangGraph 是否可用（bool）
      - max_llm_calls: LLM 最大调用次数

    Args:
        llm:                  LLM 客户端实例
        search_person_info_fn: 自定义人物检索函数
        fetch_ancient_place_map_fn: 自定义地理编码函数
        queue_hard_place_review_fn:  自定义困难地名审核函数
        generate_markdown_fn: 自定义 Markdown 生成函数
        validate_markdown_fn: 自定义 Markdown 校验函数
        max_llm_calls:        LLM 最大调用次数（默认从环境变量 STORY_AGENT_MAX_LLM_CALLS 读取）
        memory_store:         记忆存储实例
        render_pipeline:      可选渲染管线，传入 DeliverAgent 用于 HTML 渲染
            格式: {"render_html_from_markdown": Callable[[person, markdown], Tuple[html, error]]}

    Returns:
        Dict: Agent 系统字典
    """
    _sync_runtime_overrides()
    return _runners.create_story_markdown_agent(
        llm=llm,
        search_person_info_fn=search_person_info_fn,
        fetch_ancient_place_map_fn=fetch_ancient_place_map_fn,
        queue_hard_place_review_fn=queue_hard_place_review_fn,
        generate_markdown_fn=generate_markdown_fn,
        validate_markdown_fn=validate_markdown_fn,
        max_llm_calls=max_llm_calls,
        memory_store=memory_store,
        render_pipeline=render_pipeline,
    )


__all__ = [
    "create_agent_tools",
    "create_story_markdown_agent",
    "default_fetch_ancient_place_map",
    "default_queue_hard_place_review",
    "default_generate_markdown",
    "default_search_person_info",
    "default_validate_markdown",
    "generate_markdown_with_agents",
    "list_agent_tools",
]
