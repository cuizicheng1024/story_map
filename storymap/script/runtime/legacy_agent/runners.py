"""Runner 模块 — LangGraph 图构建 + 双 Runner 实现。

本模块是管线 A 的编排核心，负责：

  1. 构建 LangGraph 状态图（含 6 个节点 + Supervisor 条件路由）
  2. 提供两种 Runner 实现：
     - LangGraph Runner:  基于 langgraph 的自动编排（首选）
     - Manual Runner:     纯 Python 循环的降级实现（langgraph 不可用时自动切换）
  3. 提供便捷入口函数 generate_markdown_with_agents()

编排架构：

  LangGraph 图结构：
    START ──→ Supervisor ──条件路由──→ SearchAgent ──→ Supervisor
                          ──条件路由──→ GeocodeAgent ──→ Supervisor
                          ──条件路由──→ EditorAgent  ──→ Supervisor
                          ──条件路由──→ CriticAgent  ──→ Supervisor
                          ──条件路由──→ DeliverAgent ──→ END

  关键设计：
    - 每个工作 Agent 执行完都回到 Supervisor，由 Supervisor 统一决策下一步
    - CriticAgent 发现问题后通过 Supervisor 路由回 Editor/Search/Geocode 进行修订
    - 修订循环受 max_revisions 和 llm_calls_limit 双重约束

Runner 切换逻辑：
    LangGraph 可用 → 使用 _build_langgraph_runner()
    LangGraph 不可用 → 使用 _build_manual_runner()（纯 Python 循环，最大 16+ 次迭代）
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Tuple

# ── LangGraph 导入（可选依赖）──
try:
    from langgraph.graph import END, START, StateGraph
    _LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False

# ── 跨包依赖 ──
from ...core.project_paths import classify_story_person_authenticity

# ── 子模块导入 ──
from .llm_parser import coerce_issue             # 将原始问题字典标准化为 AgentIssue
from .memory import StoryAgentMemoryStore, get_default_memory_store  # 记忆存储
from .nodes import (
    _critic_agent_node_factory,    # CriticAgent 节点工厂
    _editor_agent_node_factory,    # EditorAgent 节点工厂
    _finish_agent_node_factory,    # DeliverAgent 节点工厂
    _map_agent_node_factory,       # GeocodeAgent 节点工厂
    _next_step_router,             # Supervisor 条件路由函数
    _search_agent_node_factory,    # SearchAgent 节点工厂
    _supervisor_node_factory,      # Supervisor 节点工厂
)
from .state import StoryAgentState, create_initial_state, merge_state, record_degraded_reason
from .tools import create_agent_tools, list_agent_tools

# ── 非认证人物拦截 ──
def _non_authentic_agent_result(person: str, reason: str, *, max_revisions: int, llm_calls_limit: int) -> Dict[str, object]:
    """当人物无法通过真实性校验时，直接返回拦截结果，不启动管线。

    这避免了为虚构人物或无法核实的历史人物浪费 LLM 预算。

    Args:
        person:           人物名
        reason:           拦截原因（如 "人物不在主数据库中"）
        max_revisions:    最大修订轮次
        llm_calls_limit:  LLM 调用上限

    Returns:
        Dict: {"markdown": "", "state": StoryAgentState}，markdown 为空字符串
    """
    issue = coerce_issue(
        field="authenticity",
        claim=str(person or ""),
        correction="改成人物库中可核实的真实人物，或先补齐可靠史料依据后再生成。",
        confidence=0.99,
        reason=f"人物真实性过滤拦截：{reason or 'non_authentic'}",
    )
    state = create_initial_state(person, max_revisions=max_revisions, llm_calls_limit=llm_calls_limit)
    state["validation"] = {
        "pass": False,
        "risk_level": "high",
        "issues": [issue],
        "notes": "人物真实性过滤拦截",
        "metrics": {},
    }
    state["critic_feedback"] = [issue]
    state["degraded_reasons"] = record_degraded_reason(state.get("degraded_reasons"), f"authenticity_filter:{reason or 'non_authentic'}")
    state["execution_trace"] = ["finish_agent"]
    state["final_markdown"] = ""
    return {"markdown": "", "state": state}


# ═══════════════════════════════════════════════════════════════════
#  LangGraph Runner — 基于 LangGraph 状态图的自动编排
# ═══════════════════════════════════════════════════════════════════

def _build_langgraph_runner(
    *,
    tools: Dict[str, Callable[..., object]],
    llm: object,
    render_pipeline: Dict[str, object] | None = None,
) -> Callable[[str, int], Dict[str, object]]:
    """构建 LangGraph Runner。

    创建并编译 LangGraph 状态图，包含 6 个节点 + Supervisor 条件路由。
    图结构：
        START → supervisor → [条件路由到各 Agent] → supervisor → ...
        finish_agent → END

    每个工作 Agent 执行完毕后无条件返回 supervisor，由 supervisor 决定下一步。
    这是典型的 Supervisor-Worker 模式，supervisor 是唯一的决策节点。

    Args:
        tools:           工具集字典（工具名 → 工具函数）
        llm:             LLM 客户端实例
        render_pipeline: 可选渲染管线，传入 DeliverAgent 用于 HTML 渲染

    Returns:
        Callable: run(person, max_revisions, llm_calls_limit) → {"markdown": str, "state": dict}
    """
    # ── 构建状态图 ──
    workflow = StateGraph(StoryAgentState)

    # 注册 6 个节点
    workflow.add_node("supervisor", _supervisor_node_factory(llm))
    workflow.add_node("search_agent", _search_agent_node_factory(tools, llm))
    workflow.add_node("map_agent", _map_agent_node_factory(tools, llm))
    workflow.add_node("editor_agent", _editor_agent_node_factory(tools, llm))
    workflow.add_node("critic_agent", _critic_agent_node_factory(tools, llm))
    workflow.add_node("finish_agent", _finish_agent_node_factory(render_pipeline))

    # ── 边配置 ──
    # START → Supervisor（唯一入口）
    workflow.add_edge(START, "supervisor")

    # Supervisor → 条件路由到各 Agent
    workflow.add_conditional_edges(
        "supervisor",
        _next_step_router,  # 路由函数：读取 state["next_step"] 决定目标
        {
            "search_agent": "search_agent",
            "map_agent": "map_agent",
            "editor_agent": "editor_agent",
            "critic_agent": "critic_agent",
            "finish_agent": "finish_agent",
        },
    )

    # 所有工作 Agent 执行完 → 回到 Supervisor
    workflow.add_edge("search_agent", "supervisor")
    workflow.add_edge("map_agent", "supervisor")
    workflow.add_edge("editor_agent", "supervisor")
    workflow.add_edge("critic_agent", "supervisor")

    # DeliverAgent → END（唯一出口）
    workflow.add_edge("finish_agent", END)

    # 编译图
    graph = workflow.compile()

    # ── 闭包：执行函数 ──
    def run(person: str, max_revisions: int = 2, llm_calls_limit: int = 0) -> Dict[str, object]:
        """运行 LangGraph 管线。

        Args:
            person:          人物名
            max_revisions:   最大修订轮次（默认 2）
            llm_calls_limit: LLM 调用上限（0 表示不限制）

        Returns:
            {"markdown": str, "state": StoryAgentState}
        """
        initial_state = create_initial_state(
            person,
            max_revisions=max_revisions,
            llm_calls_limit=llm_calls_limit,
        )
        # LangGraph 自动管理状态流转
        final_state = graph.invoke(initial_state)
        if not isinstance(final_state, dict):
            final_state = dict(initial_state)
        return {
            "markdown": str(final_state.get("final_markdown") or final_state.get("draft_markdown") or ""),
            "state": final_state,
        }

    return run


# ═══════════════════════════════════════════════════════════════════
#  Manual Runner — LangGraph 不可用时的降级实现
# ═══════════════════════════════════════════════════════════════════

def _build_manual_runner(
    *,
    tools: Dict[str, Callable[..., object]],
    llm: object,
    render_pipeline: Dict[str, object] | None = None,
) -> Callable[[str, int], Dict[str, object]]:
    """构建 Manual Runner（降级实现）。

    当 langgraph 包未安装时自动切换为此实现。通过纯 Python 循环模拟
    LangGraph 的执行流：Supervisor 决策 → 执行对应 Agent → 回到 Supervisor。

    最大迭代次数 = max(16, 8 + max_revisions * 4)，防止无限循环。

    Args:
        tools:           工具集字典
        llm:             LLM 客户端实例
        render_pipeline: 可选渲染管线，传入 DeliverAgent 用于 HTML 渲染

    Returns:
        Callable: run(person, max_revisions, llm_calls_limit) → {"markdown": str, "state": dict}
    """
    # 手动创建所有 Agent 节点
    supervisor = _supervisor_node_factory(llm)
    search_agent = _search_agent_node_factory(tools, llm)
    map_agent = _map_agent_node_factory(tools, llm)
    editor_agent = _editor_agent_node_factory(tools, llm)
    critic_agent = _critic_agent_node_factory(tools, llm)
    finish_agent = _finish_agent_node_factory(render_pipeline)

    def run(person: str, max_revisions: int = 2, llm_calls_limit: int = 0) -> Dict[str, object]:
        """手动运行管线（纯 Python 循环）。

        模拟 LangGraph 的执行流：
          1. Supervisor 决策 → 设置 next_step
          2. 根据 next_step 执行对应 Agent
          3. 回到步骤 1
          4. 直到 next_step == "finish_agent" 或超过最大迭代次数
        """
        state = create_initial_state(
            person,
            max_revisions=max_revisions,
            llm_calls_limit=llm_calls_limit,
        )

        # 最大迭代次数：为搜索→地图→编辑→审校→修订循环预留足够空间
        # 公式：基础 8 步 + 每次修订最多 4 步 × 修订次数
        max_iterations = max(16, 8 + max(0, int(max_revisions)) * 4)
        finished = False

        for _ in range(max_iterations):
            # 步骤 1：Supervisor 决策
            state = merge_state(state, supervisor(state))
            step = _next_step_router(state)

            # 步骤 2：到达终点 → 交付
            if step == "finish_agent":
                state = merge_state(state, finish_agent(state))
                finished = True
                break

            # 步骤 2：路由到对应 Agent
            if step == "search_agent":
                state = merge_state(state, search_agent(state))
                continue
            if step == "map_agent":
                state = merge_state(state, map_agent(state))
                continue
            if step == "editor_agent":
                state = merge_state(state, editor_agent(state))
                continue
            if step == "critic_agent":
                state = merge_state(state, critic_agent(state))
                continue

            # 未知步骤 → 跳出循环
            break

        # ── 超时兜底 ──
        if not finished:
            state = merge_state(
                state,
                {
                    "degraded_reasons": record_degraded_reason(
                        state.get("degraded_reasons"),
                        f"manual_runner:max_iterations_exceeded:{max_iterations}",
                    )
                },
            )
            state = merge_state(state, finish_agent(state))

        return {
            "markdown": str(state.get("final_markdown") or state.get("draft_markdown") or ""),
            "state": state,
        }

    return run


# ═══════════════════════════════════════════════════════════════════
#  主工厂函数 — 创建完整的管线 A Agent 系统
# ═══════════════════════════════════════════════════════════════════

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
    """创建完整的管线 A Agent 系统（主工厂函数）。

    内部流程：
      1. 解析记忆存储配置（支持环境变量 STORY_AGENT_ENABLE_MEMORY）
      2. 创建工具集（支持自定义实现注入）
      3. 默认使用 Manual Runner（更稳定，无外部依赖）
      4. 包装 run 函数：添加人物真实性校验 + LLM 调用限制
      5. 返回 Agent 系统字典

    Args:
        llm:                  LLM 客户端实例
        search_person_info_fn: 自定义人物检索函数
        fetch_ancient_place_map_fn: 自定义地理编码函数
        queue_hard_place_review_fn:  自定义困难地名审核函数
        generate_markdown_fn: 自定义 Markdown 生成函数
        validate_markdown_fn: 自定义 Markdown 校验函数
        max_llm_calls:        LLM 最大调用次数
        memory_store:         记忆存储实例
        render_pipeline:      可选渲染管线，传入 DeliverAgent 用于 HTML 渲染
            格式: {"render_html_from_markdown": Callable[[person, markdown], Tuple[html, error]]}

    Returns:
        {
            "tools":                工具集字典,
            "tool_specs":           工具 schema 列表,
            "run":                  bound_run(person, max_revisions, llm_calls_limit),
            "langgraph_available":  bool,
            "max_llm_calls":        int,
        }
    """
    # ── 记忆存储配置 ──
    resolved_memory_store = memory_store
    if resolved_memory_store is None:
        memory_enabled = (os.getenv("STORY_AGENT_ENABLE_MEMORY") or "").strip().lower() in {"1", "true", "yes", "on"}
        if memory_enabled:
            resolved_memory_store = get_default_memory_store()

    # ── 创建工具集 ──
    tools = create_agent_tools(
        llm=llm,
        search_person_info_fn=search_person_info_fn,
        fetch_ancient_place_map_fn=fetch_ancient_place_map_fn,
        queue_hard_place_review_fn=queue_hard_place_review_fn,
        generate_markdown_fn=generate_markdown_fn,
        validate_markdown_fn=validate_markdown_fn,
        memory_store=resolved_memory_store,
    )

    # ── 选择 Runner（默认 Manual，更稳定）──
    runner = _build_manual_runner(tools=tools, llm=llm, render_pipeline=render_pipeline)

    # ── LLM 调用上限配置 ──
    resolved_max_llm_calls = max_llm_calls
    if resolved_max_llm_calls is None:
        resolved_max_llm_calls = int(os.getenv("STORY_AGENT_MAX_LLM_CALLS", "4") or "4")

    # ── 包装 run 函数：添加真实性校验 ──
    def bound_run(person: str, max_revisions: int = 2, llm_calls_limit: Optional[int] = None) -> Dict[str, object]:
        """带真实性校验的执行函数。

        流程：
          1. 校验人物真实性（classify_story_person_authenticity）
          2. 不通过 → 返回拦截结果
          3. 通过 → 启动管线
        """
        resolved_limit = resolved_max_llm_calls if llm_calls_limit is None else int(llm_calls_limit)
        accepted, reason = classify_story_person_authenticity(person, allow_unknown=True)
        if not accepted:
            return _non_authentic_agent_result(
                str(person or "").strip(),
                str(reason or "").strip(),
                max_revisions=max_revisions,
                llm_calls_limit=resolved_limit,
            )
        return runner(person, max_revisions, resolved_limit)

    return {
        "tools": tools,
        "tool_specs": list_agent_tools(tools),
        "run": bound_run,
        "langgraph_available": _LANGGRAPH_AVAILABLE,
        "max_llm_calls": max(0, int(resolved_max_llm_calls)),
    }


# ═══════════════════════════════════════════════════════════════════
#  默认 HTML 渲染管线
# ═══════════════════════════════════════════════════════════════════

# 从 Markdown 足迹段落提取坐标的正则
_FOOTPRINT_COORD_RE = re.compile(r"`\[(\d+\.\d+),\s*(\d+\.\d+)\]`")


def _extract_points_from_markdown(markdown: str) -> List[Dict[str, object]]:
    """从 Markdown 的足迹段落中提取坐标点列表。

    匹配格式：`[lat, lng]`（如 `[29.61036,103.92698]`）。

    Args:
        markdown: Markdown 文本

    Returns:
        List[Dict]: [{"lat": float, "lon": float, "name": str}, ...]
    """
    points: List[Dict[str, object]] = []
    lines = markdown.splitlines()
    in_footprint = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### 足迹") or stripped.startswith("## 足迹"):
            in_footprint = True
            continue
        if in_footprint and stripped.startswith("#"):
            break
        if in_footprint:
            m = _FOOTPRINT_COORD_RE.search(stripped)
            if m:
                lat = float(m.group(1))
                lon = float(m.group(2))
                # 提取地名（"- " 之后，坐标之前的部分）
                name = stripped.lstrip("- ").split("`[")[0].strip()
                # 去掉括号内的现代地名备注
                name = re.sub(r"[（(].*?[）)]", "", name).strip()
                points.append({"lat": lat, "lon": lon, "name": name})
    return points


def _build_default_render_pipeline() -> Dict[str, object]:
    """构建默认的 HTML 渲染管线。

    从 Markdown 足迹段落提取坐标，使用 render_amap_html 生成
    可交互的高德地图 HTML 页面。渲染失败不丢 Markdown。

    Returns:
        {"render_html_from_markdown": Callable[[person, markdown], Tuple[html, error]]}
    """
    def _render(person: str, markdown: str) -> Tuple[str, str]:
        try:
            from storymap.script.profile.renderer import render_amap_html
            points = _extract_points_from_markdown(markdown)
            html = render_amap_html(person, points, "")
            return html, ""
        except Exception as exc:
            return "", str(exc)

    return {"render_html_from_markdown": _render}


# ═══════════════════════════════════════════════════════════════════
#  便捷入口 — 一键生成人物 Markdown
# ═══════════════════════════════════════════════════════════════════

def generate_markdown_with_agents(
    llm: object,
    person: str,
    *,
    max_revisions: Optional[int] = None,
    max_llm_calls: Optional[int] = None,
    render_pipeline: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """便捷入口函数：一键生成人物 Markdown 传记 + 可交互 HTML 地图页面。

    这是管线 A 最常用的调用方式，封装了 Agent 创建和执行的完整流程。
    默认启用 HTML 渲染（从足迹段落提取坐标 → AMap 地图）。

    Args:
        llm:            LLM 客户端实例
        person:         人物名（如 "苏轼"）
        max_revisions:  最大修订轮次（默认从 STORY_AGENT_MAX_REVISIONS 读取，兜底 1）
        max_llm_calls:  LLM 最大调用次数
        render_pipeline: 可选渲染管线，传入 DeliverAgent 用于 HTML 渲染
            格式: {"render_html_from_markdown": Callable[[person, markdown], Tuple[html, error]]}
            默认: 自动从 Markdown 足迹段落提取坐标，渲染 AMap 地图页面

    Returns:
        {
            "markdown":            str,   # 最终 Markdown 文本
            "html":                str,   # 最终 HTML 地图页面（默认渲染）
            "render_error":        str,   # HTML 渲染错误（空字符串表示成功）
            "state":               dict,  # 完整 StoryAgentState
            "tool_specs":          list,  # 工具 schema
            "langgraph_available": bool,
            "max_llm_calls":       int,
        }

    使用示例：
        # 默认生成 Markdown + HTML
        result = generate_markdown_with_agents(llm, "苏轼", max_revisions=2)
        print(result["html"])  # 可交互的高德地图 HTML 页面

        # 自定义渲染管线
        result = generate_markdown_with_agents(llm, "苏轼",
            render_pipeline={"render_html_from_markdown": my_render_fn})
    """
    if render_pipeline is None:
        render_pipeline = _build_default_render_pipeline()

    agent = create_story_markdown_agent(llm=llm, max_llm_calls=max_llm_calls, render_pipeline=render_pipeline)

    resolved_max_revisions = max_revisions
    if resolved_max_revisions is None:
        resolved_max_revisions = int(os.getenv("STORY_AGENT_MAX_REVISIONS", "5") or "5")

    result = agent["run"](person, resolved_max_revisions, agent["max_llm_calls"])
    if not isinstance(result, dict):
        return {"markdown": "", "state": {}, "tool_specs": agent["tool_specs"]}

    # 附加元信息
    result["tool_specs"] = agent["tool_specs"]
    result["langgraph_available"] = agent["langgraph_available"]
    result["max_llm_calls"] = agent["max_llm_calls"]
    return result
