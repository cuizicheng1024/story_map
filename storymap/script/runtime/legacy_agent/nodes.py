"""Agent 节点模块 — 6 个 Agent 节点的工厂函数实现。

本模块是管线 A 的执行核心，定义了所有 Agent 节点的具体行为。
每个 Agent 节点都是闭包工厂模式：工厂函数接收工具和 LLM，返回节点函数。

节点列表：
  1. _supervisor_node_factory()    — Supervisor 节点（决策中枢）
  2. _search_agent_node_factory()  — SearchAgent 节点（人物资料检索）
  3. _map_agent_node_factory()     — GeocodeAgent 节点（古地名→现代坐标）
  4. _editor_agent_node_factory()  — EditorAgent 节点（Markdown 生成/修订）
  5. _critic_agent_node_factory()  — CriticAgent 节点（质量审校）
  6. _finish_agent_node()          — DeliverAgent 节点（最终交付）

辅助函数：
  - _extract_places_for_mapping()  — 从状态中提取待地理编码的地名列表
  - _build_editor_structure()      — 构建传给 EditorAgent 的完整上下文
  - _next_step_router()            — Supervisor 条件路由函数

每个节点函数的签名统一为：
    Callable[[StoryAgentState], StoryAgentState]
    输入：当前共享状态
    输出：状态更新字典（由 LangGraph 自动 merge 回共享状态）
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

from .common import _emit
from .critic_integration import enhanced_validation          # 增强校验（集成管线 B 的结构化检测）
from .default_tools import _ensure_short_review_in_markdown, _infer_dynasty, _normalize_places
from .editor_integration import post_process_markdown         # Editor 后处理
from .fallbacks import fallback_generate_markdown, fallback_search_result, fallback_validation
from .geo_integration import get_geo_lookup                   # 地理编码查找
from .router import build_supervisor_update, resolve_next_step  # Supervisor 决策 + 路由
from .runtime import build_runtime_reflection, build_runtime_reflection_prompt
from .state import StoryAgentState, append_trace, max_revisions_limit, record_degraded_reason
from .telemetry import copy_memory_counters, update_memory_counters
from .tool_runner import ToolCallError, call_tool             # 工具调用（含重试+熔断）
from .validation_rules import (
    _caution_consistency_issues,   # 从搜索结果中提取一致性警告
    _dedupe_issues,                # 去重校验问题
    _risk_level_from_issues,       # 根据问题列表计算风险等级
    default_validate_markdown,     # 默认 Markdown 校验规则
)


# ═══════════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════════

def _extract_places_for_mapping(state: StoryAgentState) -> List[str]:
    """从共享状态中提取所有需要地理编码的地名。

    从三个来源提取地名：
      1. search_result.places  — 检索结果中的地点列表
      2. search_result.timeline — 时间线中的地点字段
      3. critic_feedback        — 审校反馈中涉及 location/timeline 的问题

    过滤规则：
      - 长度在 2-30 字符之间
      - 仅包含中文、英文、间隔号
      - 排除包含元描述标记的地名（如"补充"、"改成"、"现代地名"等）

    Args:
        state: 共享状态

    Returns:
        List[str]: 去重后的地名列表
    """
    search_result = state.get("search_result") or {}
    places_raw = search_result.get("places") if isinstance(search_result, dict) else []
    timeline_raw = search_result.get("timeline") if isinstance(search_result, dict) else []

    places: List[str] = []

    # 来源 1：search_result.places
    for item in _normalize_places(places_raw):
        name = str(item.get("name") or "").strip()
        if name:
            places.append(name)

    # 来源 2：search_result.timeline 中的地点字段
    if isinstance(timeline_raw, list):
        for item in timeline_raw:
            if not isinstance(item, dict):
                continue
            # 尝试多个可能的字段名
            place_name = str(item.get("place") or item.get("name") or item.get("location") or "").strip()
            if place_name:
                places.append(place_name)

    # 来源 3：critic_feedback 中涉及地点/时间线的问题
    for issue in state.get("critic_feedback") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("field") or "").strip() not in {"location", "timeline"}:
            continue
        claim = str(issue.get("claim") or "").strip()
        if not claim:
            continue
        # 按分隔符拆分为多个候选地名
        segments = re.split(r"[|｜/、；;，,\n]", claim)
        for segment in segments:
            candidate = re.split(r"[（(]", segment, maxsplit=1)[0].strip()
            if not candidate:
                continue
            # 长度过滤：2-30 字符
            if len(candidate) < 2 or len(candidate) > 30:
                continue
            # 字符集过滤：仅中文、英文、间隔号
            if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{2,30}", candidate):
                continue
            # 排除含数字的
            if re.search(r"\d", candidate):
                continue
            # 排除元描述标记
            if any(
                marker in candidate
                for marker in (
                    "补充", "对应", "改成", "改为", "替换", "不要",
                    "现代地名", "古地理", "现代参照", "单一现代城市",
                    "时间线", "地点", "地名", "出生地", "去世地", "事件", "条目", "范围",
                )
            ):
                continue
            places.append(candidate)

    # 去重
    deduped: List[str] = []
    seen = set()
    for place in places:
        if place in seen:
            continue
        seen.add(place)
        deduped.append(place)

    # ── P1: 拆分复合地名（"上饶、铅山" → ["上饶", "铅山"]）──
    _COMPOSITE_SPLIT_RE = re.compile(r"[，,、；;]+")
    expanded: List[str] = []
    for place in deduped:
        parts = [p.strip() for p in _COMPOSITE_SPLIT_RE.split(place) if p.strip()]
        for part in parts:
            if len(part) >= 2 and part not in expanded:
                expanded.append(part)

    # ── P2b: 包含关系去重（"巩县" ⊂ "河南巩县" → 保留短的）──
    # 同一地点的两种写法（如纯地名 vs 省份+地名）会被重复编码，
    # 这里按长度升序排列后，剔除被其他地名包含的长名。
    sorted_places = sorted(expanded, key=lambda p: len(p))
    final: List[str] = []
    for place in sorted_places:
        if any(place in other for other in final):
            # 当前地名是已有地名的子串（如 "巩县" 被 "河南巩县" 包含，
            # 但短的先被加入，所以这里实际不会发生），跳过
            continue
        # 剔除 final 中已被当前地名包含的长名
        final = [f for f in final if f not in place]
        if place not in final:
            final.append(place)
    return final


def _build_editor_structure(state: StoryAgentState) -> Dict[str, object]:
    """构建传给 EditorAgent 的完整上下文结构。

    将共享状态中的关键信息打包为 EditorAgent 需要的输入格式，
    包含运行时反射信息，帮助 Editor 做出更好的修订决策。

    Args:
        state: 共享状态

    Returns:
        Dict: {
            "person":                 人物名,
            "plan":                   执行计划,
            "search_result":          检索资料,
            "place_maps":             地名映射+坐标,
            "critic_feedback":        审校反馈,
            "previous_draft":         上一版草稿（修订时使用）,
            "runtime_reflection":     运行时反射（LLM 预算、工具状态等）,
            "runtime_reflection_prompt": 运行时反射提示文本,
        }
    """
    runtime_reflection = build_runtime_reflection(state)
    return {
        "person": state.get("person") or "",
        "plan": state.get("plan") or [],
        "search_result": state.get("search_result") or {},
        "place_maps": state.get("place_maps") or [],
        "critic_feedback": state.get("critic_feedback") or [],
        "previous_draft": state.get("draft_markdown") or "",
        "runtime_reflection": runtime_reflection,
        "runtime_reflection_prompt": build_runtime_reflection_prompt(state),
    }


# ═══════════════════════════════════════════════════════════════════
#  1. Supervisor 节点 — 决策中枢
# ═══════════════════════════════════════════════════════════════════

def _supervisor_node_factory(llm: object) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 Supervisor 节点。

    Supervisor 是整个管线的决策中枢，负责：
      1. 分析当前共享状态（是否有资料、有坐标、有草稿、有校验结果）
      2. 决策下一步路由（search_agent / map_agent / editor_agent / critic_agent / finish_agent）
      3. 通过 emit 回调输出决策日志

    Args:
        llm: LLM 客户端实例（用于 emit 日志输出）

    Returns:
        Callable: supervisor_node(state) → state_update
    """
    def supervisor_node(state: StoryAgentState) -> StoryAgentState:
        return build_supervisor_update(state, emit=lambda message: _emit(llm, message))
    return supervisor_node


# ═══════════════════════════════════════════════════════════════════
#  2. SearchAgent 节点 — 人物资料检索
# ═══════════════════════════════════════════════════════════════════

def _search_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 SearchAgent 节点。

    职责：调用 search_person_info 工具检索人物资料。
    输入：state["person"]（人物名）
    输出：state["search_result"]（包含 timeline、places、identities、achievements 等）

    防护：
      - 工具调用失败 → 降级为 fallback_search_result()（最小检索结果）
      - 每次调用计入 llm_calls_used 预算

    Args:
        tools: 工具集字典（需包含 "search_person_info" 键）
        llm:   LLM 客户端实例

    Returns:
        Callable: search_agent_node(state) → state_update
    """
    def search_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "search_agent")

        # ── P1/P2a: 修订轮跳过重复检索 ──
        # 如果 search_result 已存在且包含有效数据（有 timeline 或 places），
        # 说明之前已成功检索，无需重复消耗 LLM 预算。
        existing = state.get("search_result")
        if isinstance(existing, dict) and (
            existing.get("timeline") or existing.get("places") or existing.get("summary")
        ):
            _emit(llm, f"🔎 SearchAgent：跳过（已有 {state.get('person') or ''} 的检索结果，复用缓存）")
            return {
                "execution_trace": trace,
                "memory_hits": copy_memory_counters(state)[0],
                "memory_misses": copy_memory_counters(state)[1],
            }

        _emit(llm, f"🔎 SearchAgent：检索 {state.get('person') or ''} 的资料")

        # ── 初始化计数器 ──
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)

        try:
            # ── 调用工具（含重试 + 熔断）──
            tool_run = call_tool(
                state,
                tools["search_person_info"],
                str(state.get("person") or ""),
                agent_step="search_agent",
            )
            search_result = tool_run["result"]
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(tool_run["tool_traces"] or [])
            llm_calls_used = tool_run["llm_calls_used"]
            memory_access = tool_run["memory_access"]
            memory_hits, memory_misses = update_memory_counters(state, memory_access)
        except ToolCallError as exc:
            # ── 降级：使用最小检索结果 ──
            degraded_reasons = record_degraded_reason(degraded_reasons, f"search_agent:{exc}")
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            search_result = fallback_search_result(str(state.get("person") or ""), state)
            _emit(llm, "⚠️ SearchAgent 失败，已回退为最小检索结果")

        return {
            "search_result": search_result if isinstance(search_result, dict) else {},
            "needs_redraft": bool(state.get("draft_markdown")),  # 已有草稿则需重写
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return search_agent_node


# ═══════════════════════════════════════════════════════════════════
#  3. GeocodeAgent 节点 — 古地名→现代坐标
# ═══════════════════════════════════════════════════════════════════

def _geocode_one_place(
    place: str,
    state: StoryAgentState,
    tools: Dict[str, Callable[..., object]],
) -> Tuple[Dict[str, object], StoryAgentState, str]:
    """对单个地名执行地理编码（线程安全）。

    每次调用创建独立的 working_state 副本，不共享可变状态。

    Args:
        place: 待编码的古地名
        state: 当前共享状态（只读引用）
        tools: 工具集字典

    Returns:
        (info, state_update, error): 编码结果字典、状态更新、错误信息（空字符串表示成功）
    """
    # 每线程独立副本
    working_state: StoryAgentState = dict(state)
    working_state["tool_traces"] = list(state.get("tool_traces") or [])
    working_state["llm_calls_used"] = int(state.get("llm_calls_used") or 0)

    # ── 从检索结果中提取朝代，用于地理编码消歧 ──
    search_result = state.get("search_result")
    dynasty: Optional[str] = None
    if isinstance(search_result, dict):
        # 优先取显式 dynasty 字段，其次从 era/period 字段推断
        dynasty = search_result.get("dynasty") or search_result.get("era") or search_result.get("period")
        if isinstance(dynasty, str):
            dynasty = dynasty.strip()

    try:
        tool_run = call_tool(
            working_state,
            tools["fetch_ancient_place_map"],
            place,
            agent_step="map_agent",
            dynasty=dynasty,
        )
        info = tool_run["result"]
        return (
            info if isinstance(info, dict) else {},
            {
                "tool_traces": tool_run["tool_traces"],
                "llm_calls_used": tool_run["llm_calls_used"],
                "memory_access": tool_run.get("memory_access", {}),
            },
            "",
        )
    except ToolCallError as exc:
        return (
            {
                "query": place,
                "ancient_name": place,
                "modern_name": place,
                "lat": None,
                "lng": None,
                "source": "",
            },
            {
                "tool_traces": list(exc.tool_traces or []),
                "llm_calls_used": int(exc.llm_calls_used),
            },
            f"map_agent:{place}:{exc}",
        )
    except Exception as exc:
        return (
            {
                "query": place,
                "ancient_name": place,
                "modern_name": place,
                "lat": None,
                "lng": None,
                "source": "",
            },
            {},
            f"map_agent:{place}:{exc}",
        )


def _map_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 GeocodeAgent（内部名 map_agent）节点。

    职责：对 _extract_places_for_mapping() 提取的每个地名调用 fetch_ancient_place_map 工具，
         获取古今地名映射和 WGS84 坐标。

    优化：
      - P0: 修订轮跳过已成功编码的地名（避免重复 API 调用）
      - P3: 多地名并行编码（ThreadPoolExecutor, max_workers=5）
      - 单个地名失败返回 lat=None, lng=None，不中断管线
      - 新资料获取后设置 needs_redraft=True 触发重写

    Args:
        tools: 工具集字典（需包含 "fetch_ancient_place_map" 键）
        llm:   LLM 客户端实例

    Returns:
        Callable: map_agent_node(state) → state_update
    """
    def map_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "map_agent")
        places = _extract_places_for_mapping(state)

        # ── P0: 跳过已成功编码的地名 ──
        existing_coords: set = set()
        for pm in (state.get("place_maps") or []):
            if isinstance(pm, dict) and pm.get("lat") is not None and pm.get("lng") is not None:
                q = pm.get("query", pm.get("ancient_name", ""))
                if q:
                    existing_coords.add(q)
        pending = [p for p in places if p not in existing_coords]
        skipped = len(places) - len(pending)

        _emit(llm, f"🗺️ MapAgent：校正 {len(places)} 个地点"
              + (f"（跳过 {skipped} 个已编码）" if skipped else ""))

        # ── P3: 并行编码（多地名时使用线程池，单地名串行避免开销）──
        if len(pending) <= 1:
            # 单地名：串行执行
            all_results = []
            for p in pending:
                info, upd, err = _geocode_one_place(p, state, tools)
                all_results.append((info, upd, err))
        else:
            # 多地名：并行执行
            with ThreadPoolExecutor(max_workers=min(len(pending), 5)) as executor:
                futures = {
                    executor.submit(_geocode_one_place, p, state, tools): p
                    for p in pending
                }
                all_results = []
                for future in as_completed(futures):
                    try:
                        all_results.append(future.result())
                    except Exception as exc:
                        place = futures[future]
                        all_results.append((
                            {
                                "query": place,
                                "ancient_name": place,
                                "modern_name": place,
                                "lat": None,
                                "lng": None,
                                "source": "",
                            },
                            {},
                            f"map_agent:{place}:thread:{exc}",
                        ))

        # ── 合并结果 ──
        place_maps: List[Dict[str, object]] = list(state.get("place_maps") or [])
        tool_traces = list(state.get("tool_traces") or [])
        degraded_reasons = list(state.get("degraded_reasons") or [])
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        memory_hits, memory_misses = copy_memory_counters(state)

        for info, upd, err in all_results:
            if info:
                place_maps.append(info)
            tool_traces.extend(upd.get("tool_traces") or [])
            llm_calls_used += upd.get("llm_calls_used", 0)
            if upd.get("memory_access"):
                memory_hits, memory_misses = update_memory_counters(
                    {"memory_hits": memory_hits, "memory_misses": memory_misses},
                    upd["memory_access"],
                )
            if err:
                degraded_reasons = record_degraded_reason(degraded_reasons, err)

        return {
            "place_maps": place_maps,
            "needs_redraft": bool(state.get("draft_markdown")),
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "degraded_reasons": degraded_reasons,
            "llm_calls_used": llm_calls_used,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return map_agent_node


# ═══════════════════════════════════════════════════════════════════
#  4. EditorAgent 节点 — Markdown 生成/修订
# ═══════════════════════════════════════════════════════════════════

def _editor_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 EditorAgent 节点。

    职责：调用 generate_markdown 工具生成或修订结构化 Markdown 传记。
    输入：_build_editor_structure(state) 打包的完整上下文
    输出：state["draft_markdown"]（Markdown 草稿）

    关键处理：
      - 工具调用失败 → 降级为 fallback_generate_markdown()（确定性组装）
      - 自动确保 short_review 字段存在（_ensure_short_review_in_markdown）
      - 每次调用清空 validation（重新审校）
      - 每次调用设置 needs_redraft=False

    Args:
        tools: 工具集字典（需包含 "generate_markdown" 键）
        llm:   LLM 客户端实例

    Returns:
        Callable: editor_agent_node(state) → state_update
    """
    def editor_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "editor_agent")
        _emit(llm, "📝 EditorAgent：生成或修订 Markdown")

        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)

        try:
            tool_run = call_tool(
                state,
                tools["generate_markdown"],
                _build_editor_structure(state),
                agent_step="editor_agent",
            )
            draft_markdown = tool_run["result"]
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(tool_run["tool_traces"] or [])
            llm_calls_used = tool_run["llm_calls_used"]
        except ToolCallError as exc:
            # ── 降级：确定性 Markdown 组装 ──
            degraded_reasons = record_degraded_reason(degraded_reasons, f"editor_agent:{exc}")
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            draft_markdown = fallback_generate_markdown(_build_editor_structure(state), infer_dynasty=_infer_dynasty)
            _emit(llm, "⚠️ EditorAgent 失败，已回退为确定性 Markdown 组装")

        # ── 确保 short_review 字段存在 ──
        draft_markdown = _ensure_short_review_in_markdown(
            str(draft_markdown or ""),
            dict(state.get("search_result") or {}).get("short_review_candidate"),
        )

        return {
            "draft_markdown": str(draft_markdown or ""),
            "validation": {},          # 清空旧校验结果
            "needs_redraft": False,    # 重写标志复位
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return editor_agent_node


# ═══════════════════════════════════════════════════════════════════
#  5. CriticAgent 节点 — 质量审校
# ═══════════════════════════════════════════════════════════════════

def _critic_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 CriticAgent 节点。

    职责：对 draft_markdown 进行质量审校，检测时间线、地点、身份一致性问题。

    审校流程：
      1. LLM 校验（validate_markdown 工具）
      2. 增强校验（enhanced_validation：LLM 思考泄露、章节编号、short_review、占位符）
      3. 一致性警告合并（_caution_consistency_issues）
      4. 问题去重（_dedupe_issues）
      5. 风险等级评估（_risk_level_from_issues）

    修订逻辑：
      - 通过（pass=True）→ 设置 final_markdown，结束修订
      - 未通过 → revision_count++，设置 needs_revision=True，等待 Supervisor 路由
      - 达到 max_revisions → 强制结束修订

    Args:
        tools: 工具集字典（需包含 "validate_markdown" 键）
        llm:   LLM 客户端实例

    Returns:
        Callable: critic_agent_node(state) → state_update
    """
    def critic_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "critic_agent")
        _emit(llm, "🧪 CriticAgent：检查时间、地点和结构一致性")

        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)

        # ── 步骤 1：LLM 校验 ──
        try:
            tool_run = call_tool(
                state,
                tools["validate_markdown"],
                str(state.get("draft_markdown") or ""),
                agent_step="critic_agent",
            )
            validation = tool_run["result"]
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(tool_run["tool_traces"] or [])
            llm_calls_used = tool_run["llm_calls_used"]
        except ToolCallError as exc:
            # ── 降级：确定性校验 ──
            degraded_reasons = record_degraded_reason(degraded_reasons, f"critic_agent:{exc}")
            tool_traces = list(state.get("tool_traces") or [])
            tool_traces.extend(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            validation = fallback_validation(
                str(state.get("draft_markdown") or ""),
                person=str(state.get("person") or ""),
                validate_fn=default_validate_markdown,
            )
            _emit(llm, "⚠️ CriticAgent 失败，已回退为确定性校验")

        # ── 步骤 2：增强校验（管线 B 的结构化检测）──
        if not isinstance(validation, dict):
            validation = {"pass": False, "risk_level": "high", "issues": [], "notes": "校验器未返回字典"}

        # ── 步骤 3-4：问题合并 + 去重 ──
        merged_issues = [item for item in list(validation.get("issues") or []) if isinstance(item, dict)]
        merged_issues.extend(
            _caution_consistency_issues(
                str(state.get("draft_markdown") or ""),
                dict(state.get("search_result") or {}).get("cautions") or [],
            )
        )
        merged_issues = _dedupe_issues(merged_issues)

        # ── 步骤 5：风险等级评估 ──
        validation["issues"] = merged_issues
        validation["risk_level"] = _risk_level_from_issues(merged_issues)
        # 通过标准：没有置信度 >= 0.7 的问题
        validation["pass"] = not any(float(item.get("confidence") or 0.0) >= 0.7 for item in merged_issues)
        validation["notes"] = "" if not merged_issues else f"共发现 {len(merged_issues)} 个待核查点"

        feedback = validation.get("issues") or []
        if not isinstance(feedback, list):
            feedback = []

        updates: StoryAgentState = {
            "validation": validation,
            "critic_feedback": [item for item in feedback if isinstance(item, dict)],
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

        # ── 修订逻辑 ──
        if validation.get("pass"):
            # 通过 → 直接交付
            updates["final_markdown"] = str(state.get("draft_markdown") or "")
            updates["needs_revision"] = False
            return updates

        if int(state.get("revision_count") or 0) < max_revisions_limit(state):
            # 未通过 + 未达上限 → 进入修订循环
            updates["revision_count"] = int(state.get("revision_count") or 0) + 1
            updates["needs_revision"] = True
            updates["needs_redraft"] = False
        else:
            # 达到上限 → 强制结束
            updates["needs_revision"] = False
            updates["needs_redraft"] = False

        return updates

    return critic_agent_node


# ═══════════════════════════════════════════════════════════════════
#  6. DeliverAgent 节点 — 最终交付
# ═══════════════════════════════════════════════════════════════════

def _finish_agent_node_factory(
    render_pipeline: Dict[str, object] | None = None,
) -> Callable[[StoryAgentState], StoryAgentState]:
    """创建 DeliverAgent 节点（内部名 finish_agent）。

    职责：
      1. 从共享状态中提取最终 Markdown
      2. 若提供 render_pipeline，将 Markdown 渲染为可交互 HTML 地图页面
      3. 标记管线完成

    交付逻辑：
      - 优先取 final_markdown（CriticAgent 通过时设置）
      - 回退取 draft_markdown（未通过审校但达到轮次上限时）
      - 兜底空字符串
      - HTML 渲染失败不回退 Markdown（render_error 记录原因）

    Args:
        render_pipeline: 可选渲染管线字典，包含：
            render_html_from_markdown: Callable[[person, markdown], Tuple[html, error]]
                渲染函数，输入人物名和 Markdown，返回 (html 字符串, 错误字符串)

    Returns:
        Callable: finish_agent_node(state) → state_update
    """
    def finish_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "finish_agent")
        markdown = str(state.get("final_markdown") or state.get("draft_markdown") or "")
        person = str(state.get("person") or "")

        # ── HTML 渲染（可选）──
        html = ""
        render_error = ""
        if markdown and person and render_pipeline:
            render_fn = render_pipeline.get("render_html_from_markdown")
            if callable(render_fn):
                try:
                    html, render_error = render_fn(person, markdown)
                    if not isinstance(html, str):
                        html = ""
                    if not isinstance(render_error, str):
                        render_error = str(render_error or "")
                except Exception as exc:
                    render_error = str(exc)

        return {
            "final_markdown": markdown,
            "html": html,
            "render_error": render_error,
            "execution_trace": trace,
            "degraded_reasons": list(state.get("degraded_reasons") or []),
            "memory_hits": dict(state.get("memory_hits") or {}),
            "memory_misses": dict(state.get("memory_misses") or {}),
        }

    return finish_agent_node


# ═══════════════════════════════════════════════════════════════════
#  Supervisor 条件路由函数
# ═══════════════════════════════════════════════════════════════════

def _next_step_router(state: StoryAgentState) -> str:
    """Supervisor 条件路由函数。

    读取 state["next_step"] 决定 LangGraph 的下一个节点。
    这是 LangGraph 条件边的路由键，由 build_supervisor_update() 设置。

    Args:
        state: 共享状态

    Returns:
        str: 下一个节点名（search_agent / map_agent / editor_agent / critic_agent / finish_agent）
    """
    return resolve_next_step(state)
