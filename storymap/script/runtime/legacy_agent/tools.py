"""
┌──────────────────────────────────────────────────────────────┐
│  legacy_agent/tools.py — Agent 工具注册与元数据工厂           │
│                                                              │
│  职责：                                                      │
│    1. 创建 Agent 使用的所有工具函数（搜索、地图、编辑、审查） │
│    2. 包装记忆存储（Memory Store）的缓存读写逻辑              │
│    3. 根据 LLM 可用性动态调整工具的权限与标签                  │
│    4. 提供工具列表的元数据导出接口（list_agent_tools）        │
│                                                              │
│  设计要点：                                                  │
│    - 每个工具都通过 @tool 装饰器注册，携带 schema、超时、     │
│      重试次数、成本等级、权限、标签等元信息                   │
│    - 支持自定义实现注入（DI 模式），未注入时回退到默认实现    │
│    - 缓存命中时通过 set_memory_access 上报遥测埋点            │
└──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ...cli.tooling import tool
from .common import _fact_check_llm_enabled, _tool_uses_llm
from .constants import _EDITOR_LLM_TIMEOUT_SECONDS, _SEARCH_LLM_TIMEOUT_SECONDS
from .default_tools import (
    default_fetch_ancient_place_map,
    default_generate_markdown,
    default_queue_hard_place_review,
    default_search_person_info,
)
from .memory import StoryAgentMemoryStore
from .telemetry import set_memory_access
from .validation_rules import default_validate_markdown


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
    """
    创建并返回 Agent 所需的全部工具函数字典。

    采用依赖注入模式：每个工具均可通过外部传入的自定义实现覆盖，
    未传入时自动回退到 default_tools 中的默认实现。

    Args:
        llm:
            LLM 实例（可为 None）。用于判断工具是否需要 LLM 调用，
            以及作为默认实现中 LLM 调用的参数传入。
        search_person_info_fn:
            自定义的「人物信息检索」实现。签名：person_name -> Dict。
        fetch_ancient_place_map_fn:
            自定义的「古地名地图查询」实现。签名：place_name -> Dict。
        queue_hard_place_review_fn:
            自定义的「人工审核入队」实现。签名：payload -> Dict。
        generate_markdown_fn:
            自定义的「Markdown 生成」实现。签名：structure -> str。
        validate_markdown_fn:
            自定义的「Markdown 校验」实现。签名：content -> Dict。
        memory_store:
            可选的记忆存储实例，用于缓存查询结果，避免重复调用。

    Returns:
        Dict[str, Callable]:
            工具名 → 工具函数的映射字典，包含以下 5 个键：
            - "search_person_info"
            - "fetch_ancient_place_map"
            - "queue_hard_place_review"
            - "generate_markdown"
            - "validate_markdown"

    Raises:
        无显式异常；内部默认实现可能因 LLM 调用失败而抛出异常。
    """

    # ── 步骤 1：确定各工具的实际实现（注入优先，否则 fallback 到默认实现）──
    store = memory_store

    # 人物搜索：优先使用注入实现，否则调用 default_search_person_info（需 llm）
    search_impl = search_person_info_fn or (
        lambda person_name: default_search_person_info(person_name, llm=llm)
    )

    # 审核队列：注入实现或直接使用默认函数
    queue_impl = queue_hard_place_review_fn or default_queue_hard_place_review

    # 古地名地图：注入实现或使用默认函数（传入审核队列回调）
    map_impl = fetch_ancient_place_map_fn or (
        lambda place_name, **kw: default_fetch_ancient_place_map(
            place_name, queue_review_fn=queue_impl, **kw
        )
    )

    # Markdown 编辑器：注入实现或使用默认 LLM 生成
    editor_impl = generate_markdown_fn or (
        lambda structure: default_generate_markdown(structure, llm=llm)
    )

    # Markdown 校验器：注入实现或使用默认校验（需 llm）
    critic_impl = validate_markdown_fn or (
        lambda content: default_validate_markdown(content, person="", llm=llm)
    )

    # ── 步骤 2：判断各工具是否涉及 LLM 调用 ──
    # 人物搜索：如果用户注入了自定义实现，则信任注入方，否则依赖 llm 是否传入
    search_uses_llm = _tool_uses_llm(search_person_info_fn, default_uses_llm=llm is not None)
    # 编辑器：同理，注入时信任注入方，否则由 llm 决定
    editor_uses_llm = _tool_uses_llm(generate_markdown_fn, default_uses_llm=llm is not None)
    # 校验器：仅当使用默认实现且 LLM fact-check 启用时，才标记为 LLM 调用
    critic_uses_llm = validate_markdown_fn is None and _fact_check_llm_enabled(llm)

    # ── 步骤 3：根据 LLM 使用情况动态组装工具的标签与权限 ──
    # 人物搜索的标签
    search_tags = ["research"]
    if search_uses_llm:
        search_tags.append("llm")

    # 编辑器：使用 LLM 时需要 model_call 权限，否则只需 read
    editor_permission = "model_call" if editor_uses_llm else "read"
    editor_tags = ["editor"]
    if editor_uses_llm:
        editor_tags.append("llm")

    # 校验器：同理，LLM 模式需要 model_call
    critic_permission = "model_call" if critic_uses_llm else "read"
    critic_tags = ["critic", "quality"]
    if critic_uses_llm:
        critic_tags.append("llm_optional")

    # ── 步骤 4：定义并注册各工具函数 ──

    @tool(
        name="search_person_info",
        description="检索人物资料，并整理为结构化信息片段",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": [
                "person",
                "summary",
                "identities",
                "achievements",
                "timeline",
                "places",
                "cautions",
            ],
        },
        timeout_seconds=float(_SEARCH_LLM_TIMEOUT_SECONDS),
        retry_count=2,
        cost_tier="medium",
        permission="network_read",
        tags=search_tags,
    )
    def search_person_info(person_name: str) -> Dict[str, object]:
        """
        检索人物资料并返回结构化信息。

        优先从 memory_store 缓存中读取；缓存未命中时调用实际实现并写入缓存。

        Args:
            person_name: 要检索的人物名称。

        Returns:
            Dict 包含 person, summary, identities, achievements,
            timeline, places, cautions 等字段。

        Raises:
            取决于 search_impl 的实际行为（默认实现可能因 LLM 调用失败而抛出）。
        """
        # 尝试从记忆存储中读取缓存
        if store is not None:
            cached = store.get_person_search(person_name)
            if isinstance(cached, dict) and cached.get("person"):
                # 缓存命中：上报遥测埋点并直接返回
                set_memory_access(search_person_info, bucket="search", hit=True)
                return cached

        # 缓存未命中：上报埋点后调用实际实现
        set_memory_access(search_person_info, bucket="search", hit=False)
        result = search_impl(person_name)

        # 将有效结果写入缓存，供后续复用
        if store is not None and isinstance(result, dict) and result.get("person"):
            store.set_person_search(person_name, result)

        return result

    @tool(
        name="fetch_ancient_place_map",
        description="查询古今地名映射与现代坐标",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": [
                "query",
                "ancient_name",
                "modern_name",
                "lat",
                "lng",
                "source",
            ],
        },
        timeout_seconds=15.0,
        retry_count=1,
        cost_tier="low",
        permission="network_read",
        tags=["map", "geocode"],
    )
    def fetch_ancient_place_map(place_name: str, **extra: object) -> Dict[str, object]:
        """
        查询古地名到现代地名的映射，并返回坐标信息。

        优先从 memory_store 缓存中读取；缓存未命中时调用实际实现并写入缓存。

        Args:
            place_name: 要查询的古地名。
            **extra: 额外参数，透传给底层实现（如 dynasty="唐"）。

        Returns:
            Dict 包含 query, ancient_name, modern_name, lat, lng, source 等字段。

        Raises:
            取决于 map_impl 的实际行为。
        """
        # 尝试从记忆存储中读取缓存
        if store is not None:
            cached = store.get_place_map(place_name)
            if isinstance(cached, dict) and cached.get("query"):
                # 缓存命中：上报遥测埋点并直接返回
                set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=True)
                return cached

        # 缓存未命中：上报埋点后调用实际实现
        set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=False)
        result = map_impl(place_name, **extra)

        # 将有效结果写入缓存
        if store is not None and isinstance(result, dict) and result.get("query"):
            store.set_place_map(place_name, result)

        return result

    @tool(
        name="queue_hard_place_review",
        description="将无法稳定解析坐标的地点投递到人工审核队列",
        input_schema={
            "type": "object",
            "required": ["place_name"],
            "properties": {
                "place_name": {"type": "string"},
                "person": {"type": "string"},
                "context": {"type": "string"},
                "reason": {"type": "string"},
                "queue_json_path": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": [
                "status",
                "queued",
                "raw_place",
                "normalized_place_key",
                "recommended_search_name",
                "review_item_id",
                "queue_path",
                "reason",
            ],
        },
        timeout_seconds=8.0,
        retry_count=0,
        cost_tier="low",
        permission="write",
        tags=["map", "review_queue"],
    )
    def queue_hard_place_review(payload: Dict[str, object]) -> Dict[str, object]:
        """
        将难以自动解析坐标的地点投递到人工审核队列。

        该工具不涉及缓存逻辑，直接委托给注入或默认的队列实现。

        Args:
            payload: 字典，至少包含 place_name，可选 person/context/reason 等。

        Returns:
            Dict 包含 status, queued, raw_place, normalized_place_key 等字段。
        """
        return queue_impl(payload)

    @tool(
        name="generate_markdown",
        description="根据结构化资料与反馈生成最终 Markdown",
        input_schema={
            "type": "object",
            "required": [
                "person",
                "plan",
                "search_result",
                "place_maps",
                "critic_feedback",
                "previous_draft",
            ],
        },
        output_schema={"type": "string"},
        timeout_seconds=float(_EDITOR_LLM_TIMEOUT_SECONDS),
        retry_count=1,
        cost_tier="high",
        permission=editor_permission,
        tags=editor_tags,
    )
    def generate_markdown(structure: Dict[str, object]) -> str:
        """
        根据结构化资料与审查反馈生成最终的 Markdown 文档。

        Args:
            structure: 包含 person, plan, search_result, place_maps,
                       critic_feedback, previous_draft 等字段的结构化输入。

        Returns:
            str: 生成的 Markdown 内容。

        Raises:
            取决于 editor_impl 的实际行为（默认实现依赖 LLM 调用）。
        """
        return editor_impl(structure)

    @tool(
        name="validate_markdown",
        description="检查 Markdown 的完整性、一致性与地名精度",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": ["pass", "risk_level", "issues", "notes"],
        },
        timeout_seconds=20.0,
        retry_count=0,
        cost_tier="low",
        permission=critic_permission,
        tags=critic_tags,
    )
    def validate_markdown(content: str) -> Dict[str, object]:
        """
        校验 Markdown 文档的质量，包括完整性、一致性和地名精度。

        Args:
            content: 待校验的 Markdown 字符串。

        Returns:
            Dict 包含 pass（是否通过）、risk_level（风险等级）、
            issues（问题列表）、notes（备注）等字段。
        """
        return critic_impl(content)

    # ── 步骤 5：组装并返回工具字典 ──
    return {
        "search_person_info": search_person_info,
        "fetch_ancient_place_map": fetch_ancient_place_map,
        "queue_hard_place_review": queue_hard_place_review,
        "generate_markdown": generate_markdown,
        "validate_markdown": validate_markdown,
    }


def list_agent_tools(tools: Dict[str, Callable[..., object]]) -> List[Dict[str, object]]:
    """
    从工具字典中提取各工具的元数据，返回结构化的工具列表。

    遍历字典中的每个工具函数，读取其 @tool 装饰器挂载的 __tool__ 属性，
    抽取 name、description、超时、重试次数、成本等级、权限、标签等信息。

    该接口通常用于向外部系统（如 Agent 编排器、UI 面板）暴露工具能力清单。

    Args:
        tools: create_agent_tools 返回的工具字典。

    Returns:
        List[Dict[str, object]]:
            每个元素是一个工具元数据字典，包含以下字段：
            - key:           工具在字典中的键名
            - name:          工具名称（来自 @tool 装饰器）
            - description:   工具描述
            - timeout_seconds: 超时时间（秒）
            - retry_count:   重试次数
            - cost_tier:     成本等级（low / medium / high）
            - permission:    权限类型（read / write / network_read / model_call）
            - tags:          标签列表
    """
    items: List[Dict[str, object]] = []

    for key, func in tools.items():
        # 读取 @tool 装饰器挂载在函数上的元数据对象
        meta = getattr(func, "__tool__", None)
        if meta is None:
            # 跳过未被 @tool 装饰的函数（理论上不会发生，此处为防御性编程）
            continue

        items.append(
            {
                "key": key,
                "name": meta.name,
                "description": meta.description,
                "timeout_seconds": meta.timeout_seconds,
                "retry_count": meta.retry_count,
                "cost_tier": meta.cost_tier,
                "permission": meta.permission,
                "tags": list(meta.tags),
            }
        )

    return items
