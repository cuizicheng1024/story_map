"""
运行时快照与反思模块（legacy_agent runtime 子模块）。

本模块负责将 Agent 运行时的内部状态（LLM 调用次数、工具调用追踪、
修订轮次、记忆命中/未命中、降级原因等）统一抽象为结构化的运行时快照
（runtime snapshot），并在此基础上构建 PDCA 循环视图、人机料法环测质量
框架视图以及运行时反思（reflection）视图。

主要职责：
1. 类型定义：定义运行时快照、反思摘要、PDCA / 质量框架等 TypedDict 结构。
2. 快照归一化：从任意来源对象中提取、清洗、归一化为标准运行时快照。
3. 元数据抽取：从快照中抽取 AgentRuntimeMetadata 供下游消费。
4. PDCA 构建：基于快照构建 Plan-Do-Check-Act 四段结构。
5. 质量框架构建：基于快照构建人机料法环测六要素质量视图。
6. 运行时反思：综合快照数据生成 strengths / bottlenecks / suggested_actions。
7. 聚合：跨多人物汇总运行时元数据，生成 AggregatedRuntimeMetadata。
"""
from __future__ import annotations

from typing import Dict, List, TypedDict

from ..task_schema import (
    AggregatedRuntimeMetadata,
    AgentRuntimeMetadata,
    normalize_agent_runtime_metadata,
    normalize_aggregated_runtime_meta,
)


# ── 类型定义：运行时快照 ──────────────────────────────────────────────


class StoryAgentRuntimeSnapshot(TypedDict, total=False):
    """单个人物的运行时快照，记录 Agent 执行过程的关键上下文。

    字段说明：
        person: 人物标识（如人名）。
        max_llm_calls: LLM 调用最大次数限制。
        langgraph_available: LangGraph 是否可用。
        tool_specs: 工具规格列表。
        state: 运行时状态快照（见 StoryAgentRuntimeStateSnapshot）。
        fallback: 降级（fallback）策略标识。
        error: 运行错误信息。
        used_legacy_fallback: 是否启用了 legacy 降级收口。
        legacy_markdown_ok: legacy 降级产出的 Markdown 是否可用。
    """
    person: str
    max_llm_calls: int
    langgraph_available: bool
    tool_specs: List[Dict[str, object]]
    state: Dict[str, object]
    fallback: str
    error: str
    used_legacy_fallback: bool
    legacy_markdown_ok: bool


class StoryAgentRuntimeStateSnapshot(TypedDict, total=False):
    """运行时状态快照，记录 Agent 执行过程中的细粒度状态数据。

    字段说明：
        llm_calls_used / llm_calls_limit: LLM 调用已使用 / 上限。
        revision_count / max_revisions: 修订轮次 / 最大修订轮次。
        needs_revision: 是否需要进入修订轮次。
        needs_redraft: 是否需要完全重写。
        degraded_reasons: 降级原因列表。
        execution_trace: 执行步骤追踪列表。
        tool_traces: 工具调用追踪列表（含 tool_name、success、duration_ms 等）。
        memory_hits / memory_misses: 记忆命中 / 未命中桶统计。
        plan: 执行计划列表。
        search_result: 检索结果。
        place_maps: 地点映射结果列表。
        draft_markdown: 草稿 Markdown。
        final_markdown: 最终 Markdown。
        validation: 校验结果（含 pass、risk_level 等）。
        critic_feedback: Critic 反馈列表。
    """
    llm_calls_used: int
    llm_calls_limit: int
    revision_count: int
    max_revisions: int
    needs_revision: bool
    needs_redraft: bool
    degraded_reasons: List[str]
    execution_trace: List[str]
    tool_traces: List[Dict[str, object]]
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]
    plan: List[str]
    search_result: Dict[str, object]
    place_maps: List[Dict[str, object]]
    draft_markdown: str
    final_markdown: str
    validation: Dict[str, object]
    critic_feedback: List[Dict[str, object]]


# ── 类型定义：运行时反思 ──────────────────────────────────────────────


class RuntimeReflectionLlmBudget(TypedDict, total=False):
    """LLM 预算使用情况。

    字段说明：
        used / limit: 已使用次数 / 上限。
        utilization: 使用率（used / limit）。
        near_limit: 是否接近上限。
    """
    used: int
    limit: int
    utilization: float
    near_limit: bool


class RuntimeReflectionRetrySummary(TypedDict, total=False):
    """重试 / 修订摘要。

    字段说明：
        revision_count / max_revisions: 修订轮次 / 上限。
        critic_passes: Critic 通过次数。
        editor_passes: Editor 通过次数。
    """
    revision_count: int
    max_revisions: int
    critic_passes: int
    editor_passes: int


class RuntimeReflectionToolSummary(TypedDict, total=False):
    """工具调用摘要。

    字段说明：
        total_calls / failed_calls / timed_out_calls: 总调用 / 失败 / 超时次数。
        success_rate: 成功率（0.0 ~ 1.0）。
    """
    total_calls: int
    failed_calls: int
    timed_out_calls: int
    success_rate: float


class RuntimeReflectionMemorySummary(TypedDict, total=False):
    """记忆摘要。

    字段说明：
        hit_count / miss_count: 命中 / 未命中次数。
        hit_buckets / miss_buckets: 命中 / 未命中的桶名列表。
    """
    hit_count: int
    miss_count: int
    hit_buckets: List[str]
    miss_buckets: List[str]


class StoryAgentRuntimeReflection(TypedDict, total=False):
    """运行时反思综合视图。

    字段说明：
        status: 状态（stable / watch / degraded / empty）。
        strengths: 优势列表。
        bottlenecks: 瓶颈列表。
        suggested_actions: 建议动作列表。
        llm_budget: LLM 预算。
        retry_summary: 重试摘要。
        tool_summary: 工具调用摘要。
        memory_summary: 记忆摘要。
    """
    status: str
    strengths: List[str]
    bottlenecks: List[str]
    suggested_actions: List[str]
    llm_budget: RuntimeReflectionLlmBudget
    retry_summary: RuntimeReflectionRetrySummary
    tool_summary: RuntimeReflectionToolSummary
    memory_summary: RuntimeReflectionMemorySummary


# ── 类型定义：PDCA 循环 ────────────────────────────────────────────────


class RuntimePdcaSection(TypedDict, total=False):
    """PDCA 单个阶段的节结构。

    字段说明：
        summary: 阶段摘要（一句话描述）。
        items: 阶段明细条目列表。
    """
    summary: str
    items: List[str]


class StoryAgentRuntimePdca(TypedDict, total=False):
    """PDCA 循环视图（Plan-Do-Check-Act）。

    字段说明：
        status: 整体状态。
        person: 人物标识。
        plan / do / check / act: 四个阶段的 RuntimePdcaSection。
    """
    status: str
    person: str
    plan: RuntimePdcaSection
    do: RuntimePdcaSection
    check: RuntimePdcaSection
    act: RuntimePdcaSection


# ── 类型定义：人机料法环测质量框架 ─────────────────────────────────────


class RuntimeQualitySection(TypedDict, total=False):
    """质量框架单个维度的节结构。

    字段说明：
        label: 维度标签（人 / 机 / 料 / 法 / 环 / 测）。
        summary: 维度摘要。
        findings: 发现的问题列表。
        repair_actions: 修复动作列表。
    """
    label: str
    summary: str
    findings: List[str]
    repair_actions: List[str]


class StoryAgentRuntimeQualityFramework(TypedDict, total=False):
    """人机料法环测质量框架视图。

    字段说明：
        status: 整体状态。
        person: 人物标识。
        human / machine / material / method / environment / measurement:
            六个维度的 RuntimeQualitySection。
    """
    status: str
    person: str
    human: RuntimeQualitySection
    machine: RuntimeQualitySection
    material: RuntimeQualitySection
    method: RuntimeQualitySection
    environment: RuntimeQualitySection
    measurement: RuntimeQualitySection


# ══════════════════════════════════════════════════════════════════════
#  内部工具函数
# ══════════════════════════════════════════════════════════════════════


def _safe_int(value: object, default: int = 0) -> int:
    """安全地将任意值转换为 int，转换失败时返回 default。

    Args:
        value: 待转换的值，可以是任意类型。
        default: 转换失败时的默认返回值，默认为 0。

    Returns:
        转换后的 int 值。
    """
    try:
        return int(value)
    except Exception:
        return int(default)


def _normalize_runtime_state_snapshot(source: object) -> StoryAgentRuntimeStateSnapshot:
    """将任意来源对象归一化为 StoryAgentRuntimeStateSnapshot。

    对每个字段做类型清洗和空值保护：
    - 数字字段通过 _safe_int 安全转换。
    - 布尔字段通过 bool() 强制转换。
    - 列表字段过滤空字符串项或非 dict 项。
    - dict 字段确保类型安全并过滤空 key。

    Args:
        source: 待归一化的来源对象，预期为 dict 或类似结构。

    Returns:
        清洗后的 StoryAgentRuntimeStateSnapshot。
    """
    state = dict(source or {}) if isinstance(source, dict) else {}
    return {
        "llm_calls_used": _safe_int(state.get("llm_calls_used")),
        "llm_calls_limit": _safe_int(state.get("llm_calls_limit")),
        "revision_count": _safe_int(state.get("revision_count")),
        "max_revisions": _safe_int(state.get("max_revisions")),
        "needs_revision": bool(state.get("needs_revision")),
        "needs_redraft": bool(state.get("needs_redraft")),
        # 过滤空字符串项
        "degraded_reasons": [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()],
        "execution_trace": [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()],
        # 只保留 dict 类型的工具追踪项
        "tool_traces": [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)],
        # 过滤空 key 的记忆桶
        "memory_hits": {str(key): _safe_int(value) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()},
        "memory_misses": {
            str(key): _safe_int(value) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()
        },
        "plan": [str(item) for item in list(state.get("plan") or []) if str(item).strip()],
        # dict 字段：确保类型安全
        "search_result": dict(state.get("search_result") or {}) if isinstance(state.get("search_result"), dict) else {},
        "place_maps": [dict(item) for item in list(state.get("place_maps") or []) if isinstance(item, dict)],
        "draft_markdown": str(state.get("draft_markdown") or ""),
        "final_markdown": str(state.get("final_markdown") or ""),
        "validation": dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {},
        "critic_feedback": [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)],
    }


def _runtime_snapshot_from(source: object) -> StoryAgentRuntimeSnapshot:
    """从来源对象中提取 StoryAgentRuntimeSnapshot。

    优先尝试通过 last_agent_runtime 属性访问，回退到直接使用 source 本身。
    内部的 state 子字段会经过 _normalize_runtime_state_snapshot 归一化。

    Args:
        source: 来源对象，可以是带 last_agent_runtime 属性的对象或 dict。

    Returns:
        StoryAgentRuntimeSnapshot，若 source 无效则返回空 dict。
    """
    # 优先通过属性访问，回退到直接使用 source
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict) or not runtime:
        return {}
    state = _normalize_runtime_state_snapshot(runtime.get("state"))
    return {
        "person": str(runtime.get("person") or ""),
        "max_llm_calls": runtime.get("max_llm_calls"),
        "langgraph_available": bool(runtime.get("langgraph_available")),
        "tool_specs": list(runtime.get("tool_specs") or []),
        "state": dict(state or {}),
        "fallback": str(runtime.get("fallback") or ""),
        "error": str(runtime.get("error") or ""),
        "used_legacy_fallback": bool(runtime.get("used_legacy_fallback")),
        "legacy_markdown_ok": bool(runtime.get("legacy_markdown_ok")),
    }


def _trace_step_count(trace: List[str], name: str) -> int:
    """统计 execution_trace 中指定步骤名称出现的次数。

    Args:
        trace: 执行步骤追踪列表。
        name: 要匹配的步骤名称。

    Returns:
        匹配到的次数。
    """
    return sum(1 for item in trace if str(item or "").strip() == name)


def _tool_summary(tool_traces: List[Dict[str, object]]) -> RuntimeReflectionToolSummary:
    """从工具调用追踪列表中生成工具调用摘要。

    统计总调用次数、失败次数、超时次数，并计算成功率（0.0 ~ 1.0）。

    Args:
        tool_traces: 工具调用追踪列表，每项为包含 success、timed_out 等字段的 dict。

    Returns:
        RuntimeReflectionToolSummary，包含 total_calls、failed_calls、timed_out_calls、success_rate。
    """
    total_calls = len(tool_traces)
    # 统计 failed_calls：success 字段不为 True 的项
    failed_calls = sum(1 for item in tool_traces if isinstance(item, dict) and not bool(item.get("success", True)))
    # 统计 timed_out_calls：timed_out 字段为 True 的项
    timed_out_calls = sum(1 for item in tool_traces if isinstance(item, dict) and bool(item.get("timed_out")))
    success_rate = 1.0
    if total_calls > 0:
        success_rate = max(0.0, min(1.0, float(total_calls - failed_calls) / float(total_calls)))
    return {
        "total_calls": total_calls,
        "failed_calls": failed_calls,
        "timed_out_calls": timed_out_calls,
        "success_rate": round(success_rate, 4),
    }


def _memory_summary(memory_hits: Dict[str, int], memory_misses: Dict[str, int]) -> RuntimeReflectionMemorySummary:
    """从记忆命中/未命中桶统计数据中生成记忆摘要。

    Args:
        memory_hits: 记忆命中桶统计（桶名 -> 命中次数）。
        memory_misses: 记忆未命中桶统计（桶名 -> 未命中次数）。

    Returns:
        RuntimeReflectionMemorySummary，包含总命中/未命中次数及活跃桶名列表。
    """
    return {
        "hit_count": sum(int(value or 0) for value in memory_hits.values()),
        "miss_count": sum(int(value or 0) for value in memory_misses.values()),
        # 只列出有实际命中/未命中的桶
        "hit_buckets": [str(key) for key, value in memory_hits.items() if int(value or 0) > 0],
        "miss_buckets": [str(key) for key, value in memory_misses.items() if int(value or 0) > 0],
    }


def _final_validation_is_clean(result: Dict[str, object], runtime_snapshot: StoryAgentRuntimeSnapshot) -> bool:
    """判断最终校验是否通过（即 validation.pass 为 True）。

    优先从 result 的 _validation 字段取值，回退到 runtime_snapshot 的 state.validation。

    Args:
        result: 结果 dict，可能包含 _validation 字段。
        runtime_snapshot: 运行时快照。

    Returns:
        校验通过返回 True，否则返回 False。
    """
    validation = result.get("_validation")
    if not isinstance(validation, dict):
        # 回退到 runtime snapshot 中的 validation
        state = dict(runtime_snapshot.get("state") or {})
        validation = state.get("validation")
    if not isinstance(validation, dict) or not validation:
        return False
    return bool(validation.get("pass"))


def _runtime_state_from_source(source: object) -> Dict[str, object]:
    """从来源对象中提取运行时状态 dict。

    优先通过 last_agent_runtime.state 取值，若 state 不是 dict 则回退到整个 runtime。

    Args:
        source: 来源对象。

    Returns:
        运行时状态 dict。
    """
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict) or not runtime:
        return {}
    if isinstance(runtime.get("state"), dict):
        return dict(runtime.get("state") or {})
    return dict(runtime)


def _pdca_summary(items: List[str], empty_summary: str, ok_summary: str) -> str:
    """根据 items 是否为空返回对应的摘要文本。

    Args:
        items: 条目列表。
        empty_summary: items 为空时使用的摘要文本。
        ok_summary: items 非空时使用的摘要文本。

    Returns:
        对应的摘要文本。
    """
    return ok_summary if items else empty_summary


def _quality_section(
    label: str,
    findings: List[str],
    repair_actions: List[str],
    *,
    empty_summary: str,
    ok_summary: str,
) -> RuntimeQualitySection:
    """构建质量框架单个维度的 RuntimeQualitySection。

    自动过滤空字符串的 findings 和 repair_actions。

    Args:
        label: 维度标签（如 "人"、"机"、"料"）。
        findings: 发现的问题列表。
        repair_actions: 修复动作列表。
        empty_summary: findings 为空时使用的摘要文本。
        ok_summary: findings 非空时使用的摘要文本。

    Returns:
        清洗后的 RuntimeQualitySection。
    """
    cleaned_findings = [str(item) for item in findings if str(item).strip()]
    cleaned_actions = [str(item) for item in repair_actions if str(item).strip()]
    return {
        "label": label,
        "summary": ok_summary if cleaned_findings else empty_summary,
        "findings": cleaned_findings,
        "repair_actions": cleaned_actions,
    }


# ══════════════════════════════════════════════════════════════════════
#  公开 API：运行时快照构建与归一化
# ══════════════════════════════════════════════════════════════════════


def normalize_runtime_snapshot(source: object) -> StoryAgentRuntimeSnapshot:
    """将任意来源对象归一化为标准 StoryAgentRuntimeSnapshot。

    处理两种场景：
    1. 来源对象已包含 state 子字段 → 直接调用 _runtime_snapshot_from 提取。
    2. 来源对象将 state 字段扁平化在顶层（如 llm_calls_used 等字段直接
       出现在 runtime dict 中）→ 先检测是否有这些扁平字段，若有则整体作为
       state 传入 _normalize_runtime_state_snapshot。

    Args:
        source: 来源对象，可以是带 last_agent_runtime 属性的对象或 dict。

    Returns:
        归一化后的 StoryAgentRuntimeSnapshot。若 source 无效则返回空 dict。
    """
    # 优先通过属性访问
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict) or not runtime:
        return {}
    # ── 检测是否为扁平化格式：顶层直接包含 state 内部字段 ──
    if "state" not in runtime and any(
        key in runtime
        for key in (
            "llm_calls_used",
            "llm_calls_limit",
            "revision_count",
            "max_revisions",
            "needs_revision",
            "needs_redraft",
            "degraded_reasons",
            "execution_trace",
            "tool_traces",
            "memory_hits",
            "memory_misses",
            "plan",
            "search_result",
            "place_maps",
            "draft_markdown",
            "final_markdown",
            "validation",
            "critic_feedback",
        )
    ):
        # 扁平格式：整个 runtime 本身就是 state
        return {
            "person": str(runtime.get("person") or ""),
            "max_llm_calls": runtime.get("max_llm_calls"),
            "langgraph_available": bool(runtime.get("langgraph_available")),
            "tool_specs": list(runtime.get("tool_specs") or []),
            "state": _normalize_runtime_state_snapshot(runtime),
            "fallback": str(runtime.get("fallback") or ""),
            "error": str(runtime.get("error") or ""),
            "used_legacy_fallback": bool(runtime.get("used_legacy_fallback")),
            "legacy_markdown_ok": bool(runtime.get("legacy_markdown_ok")),
        }
    # 标准格式：state 作为子字段
    return _runtime_snapshot_from(runtime)


def build_runtime_snapshot(
    person: str,
    result: object = None,
    *,
    fallback: str = "",
    error: str = "",
) -> StoryAgentRuntimeSnapshot:
    """基于人物标识和运行结果构建运行时快照。

    先通过 normalize_runtime_snapshot 归一化 result，然后覆盖 person 并补充
    fallback / error 等元信息。若 result 为 dict，还会覆盖 max_llm_calls、
    langgraph_available、tool_specs 和 state 字段。

    Args:
        person: 人物标识（如人名）。
        result: 运行结果对象，可选。
        fallback: 降级策略标识，默认为空字符串。
        error: 运行错误信息，默认为空字符串。

    Returns:
        构建好的 StoryAgentRuntimeSnapshot。
    """
    snapshot = normalize_runtime_snapshot(result)
    snapshot["person"] = str(person or "")
    # 若 result 为 dict，从中提取额外字段覆盖 snapshot
    if isinstance(result, dict):
        state = _normalize_runtime_state_snapshot(result.get("state"))
        snapshot["max_llm_calls"] = result.get("max_llm_calls")
        snapshot["langgraph_available"] = bool(result.get("langgraph_available"))
        snapshot["tool_specs"] = list(result.get("tool_specs") or [])
        snapshot["state"] = dict(state or {})
    if fallback:
        snapshot["fallback"] = str(fallback)
    if error:
        snapshot["error"] = str(error)
    return snapshot


def mark_runtime_legacy_fallback(
    runtime: object,
    *,
    person: str,
    markdown: object,
) -> StoryAgentRuntimeSnapshot:
    """标记运行时已启用 legacy 降级收口。

    在归一化后的快照上设置 used_legacy_fallback = True 并根据 markdown 是否
    非空来设置 legacy_markdown_ok。

    Args:
        runtime: 运行时对象。
        person: 人物标识，用于覆盖 snapshot 中的 person。
        markdown: 降级产出的 Markdown 内容。

    Returns:
        标记后的 StoryAgentRuntimeSnapshot。
    """
    snapshot = normalize_runtime_snapshot(runtime)
    snapshot["person"] = str(snapshot.get("person") or person or "")
    snapshot["used_legacy_fallback"] = True
    # 非空 markdown 视为降级产出可用
    snapshot["legacy_markdown_ok"] = bool(str(markdown or "").strip())
    return snapshot


def extract_agent_runtime_metadata(source: object) -> AgentRuntimeMetadata:
    """从来源对象中抽取 AgentRuntimeMetadata。

    先归一化快照，再提取关键字段（person、langgraph_available、降级状态、
    错误信息、LLM 预算、工具追踪、记忆统计等），最后通过
    normalize_agent_runtime_metadata 做进一步归一化。

    Args:
        source: 来源对象。

    Returns:
        归一化后的 AgentRuntimeMetadata。
    """
    snapshot = normalize_runtime_snapshot(source)
    state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
    return normalize_agent_runtime_metadata(
        {
            "person": str(snapshot.get("person") or ""),
            "langgraph_available": bool(snapshot.get("langgraph_available")),
            "used_legacy_fallback": bool(snapshot.get("used_legacy_fallback")),
            "legacy_markdown_ok": bool(snapshot.get("legacy_markdown_ok")),
            "fallback": str(snapshot.get("fallback") or ""),
            "error": str(snapshot.get("error") or ""),
            "max_llm_calls": snapshot.get("max_llm_calls"),
            "tool_specs": list(snapshot.get("tool_specs") or []),
            "llm_calls_used": state.get("llm_calls_used"),
            "llm_calls_limit": state.get("llm_calls_limit"),
            "degraded_reasons": list(state.get("degraded_reasons") or []),
            "execution_trace": list(state.get("execution_trace") or []),
            "tool_traces": list(state.get("tool_traces") or []),
            "memory_hits": dict(state.get("memory_hits") or {}),
            "memory_misses": dict(state.get("memory_misses") or {}),
        }
    )


# ══════════════════════════════════════════════════════════════════════
#  公开 API：PDCA 循环视图
# ══════════════════════════════════════════════════════════════════════


def build_runtime_pdca(source: object) -> StoryAgentRuntimePdca:
    """基于运行时快照构建 PDCA（Plan-Do-Check-Act）循环视图。

    PDCA 四个阶段的含义：
    - Plan：执行计划（SearchAgent → MapAgent → EditorAgent → CriticAgent + LLM 预算）。
    - Do：执行动作（从 tool_traces 提取每次工具调用的摘要）。
    - Check：检查结果（Critic 校验结果、反馈数量、运行时反思状态与瓶颈）。
    - Act：处置动作（修订轮次、降级、fallback、进入下一轮或 FinishAgent）。

    Args:
        source: 来源对象。

    Returns:
        StoryAgentRuntimePdca，包含 plan / do / check / act 四个节。
        若 source 无效，返回 status="empty" 的空视图。
    """
    snapshot = normalize_runtime_snapshot(source)
    # ── 空快照处理 ──
    if not snapshot:
        return {
            "status": "empty",
            "person": "",
            "plan": {"summary": "当前没有可用的执行计划。", "items": []},
            "do": {"summary": "当前没有可用的执行动作。", "items": []},
            "check": {"summary": "当前没有可用的检查结果。", "items": []},
            "act": {"summary": "当前没有可用的处置动作。", "items": []},
        }

    # ── 提取 state 原始数据 ──
    state = _runtime_state_from_source(source)
    trace = [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()]
    tool_traces = [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)]
    validation = dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {}
    feedback = [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)]
    degraded_reasons = [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()]
    revision_count = _safe_int(state.get("revision_count"))
    max_revisions = _safe_int(state.get("max_revisions"))

    # ── 构建 Plan 节 ──
    plan_items = [str(item) for item in list(state.get("plan") or []) if str(item).strip()]
    # 若无显式计划，使用默认四阶段计划
    if not plan_items:
        plan_items = [
            "SearchAgent 检索人物资料",
            "MapAgent 补齐古今地名与坐标",
            "EditorAgent 生成或修订 Markdown",
            "CriticAgent 做结构与事实一致性检查",
        ]
    llm_limit = _safe_int(state.get("llm_calls_limit"))
    if llm_limit > 0:
        plan_items.append(f"LLM 预算上限 {llm_limit} 次")

    # ── 构建 Do 节 ──
    do_items: List[str] = []
    for item in tool_traces:
        tool_name = str(item.get("tool_name") or "").strip() or "unknown_tool"
        agent_step = str(item.get("agent_step") or "").strip() or "unknown_agent"
        success = "成功" if bool(item.get("success", True)) else "失败"
        duration_ms = _safe_int(item.get("duration_ms"))
        do_items.append(f"{agent_step} 调用 {tool_name}，{success}，{duration_ms}ms")
    # 若无工具追踪但有执行步骤，用 trace 兜底
    if not do_items and trace:
        do_items = [f"执行步骤：{item}" for item in trace]

    # ── 构建 Check 节 ──
    check_items: List[str] = []
    if validation:
        passed = "通过" if bool(validation.get("pass")) else "未通过"
        risk = str(validation.get("risk_level") or "unknown").strip() or "unknown"
        check_items.append(f"Critic 校验{passed}，风险等级 {risk}")
    if feedback:
        check_items.append(f"Critic 给出 {len(feedback)} 条修订建议")
    reflection = build_runtime_reflection(source)
    if str(reflection.get("status") or "").strip():
        check_items.append(f"运行态评估状态：{str(reflection.get('status') or '').strip()}")
    bottlenecks = [str(item) for item in list(reflection.get("bottlenecks") or []) if str(item).strip()]
    if bottlenecks:
        check_items.append(f"当前瓶颈：{'；'.join(bottlenecks[:3])}")

    # ── 构建 Act 节 ──
    act_items: List[str] = []
    if revision_count > 0 or max_revisions > 0:
        act_items.append(f"修订轮次 {revision_count}/{max_revisions}")
    if bool(snapshot.get("used_legacy_fallback")):
        act_items.append("已启用 legacy fallback 收口")
    fallback = str(snapshot.get("fallback") or "").strip()
    if fallback:
        act_items.append(f"fallback：{fallback}")
    if degraded_reasons:
        act_items.append(f"降级原因：{'；'.join(degraded_reasons[:3])}")
    # 判断最终状态：已进入 FinishAgent / 需修订 / 运行异常
    if "finish_agent" in trace:
        act_items.append("已进入 FinishAgent 并输出最终结果")
    elif bool(state.get("needs_revision")):
        act_items.append("进入下一轮修订")
    elif snapshot.get("state") and str(snapshot.get("error") or "").strip():
        act_items.append(f"运行异常：{str(snapshot.get('error') or '').strip()}")

    return {
        "status": str(reflection.get("status") or "stable"),
        "person": str(snapshot.get("person") or ""),
        "plan": {
            "summary": _pdca_summary(plan_items, "当前没有可用的执行计划。", "已生成本轮执行计划。"),
            "items": plan_items,
        },
        "do": {
            "summary": _pdca_summary(do_items, "当前没有记录到执行动作。", "已记录本轮执行动作。"),
            "items": do_items,
        },
        "check": {
            "summary": _pdca_summary(check_items, "当前没有检查结果。", "已记录校验与运行态检查结果。"),
            "items": check_items,
        },
        "act": {
            "summary": _pdca_summary(act_items, "当前没有后续处置动作。", "已记录修订、降级或收口动作。"),
            "items": act_items,
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  公开 API：人机料法环测质量框架
# ══════════════════════════════════════════════════════════════════════


def build_runtime_quality_framework(source: object) -> StoryAgentRuntimeQualityFramework:
    """基于运行时快照构建人机料法环测（5M1E）质量框架视图。

    六个维度的含义：
    - 人（human）：Supervisor 编排、执行步骤、Critic 反馈、人工介入点。
    - 机（machine）：工具调用统计、LLM 预算、fallback 状态。
    - 料（material）：检索资料、地点映射、草稿/最终 Markdown、校验结果。
    - 法（method）：工作流主线、修订轮次、降级原因、fallback 策略。
    - 环（environment）：LangGraph 可用性、缓存命中/未命中、工具超时。
    - 测（measurement）：execution_trace、tool_traces、validation、PDCA/reflection 状态。

    Args:
        source: 来源对象。

    Returns:
        StoryAgentRuntimeQualityFramework，包含六个维度的 RuntimeQualitySection。
        若 source 无效，返回 status="empty" 的空视图（每个维度含默认 repair_actions）。
    """
    snapshot = normalize_runtime_snapshot(source)
    # ── 空快照处理：返回带默认修复动作的空视图 ──
    if not snapshot:
        return {
            "status": "empty",
            "person": "",
            "human": _quality_section("人", [], ["先补齐本次运行的任务上下文和负责人。"], empty_summary="当前没有可用的人因信息。", ok_summary="已记录人因信息。"),
            "machine": _quality_section("机", [], ["先确认 LLM、工具执行器和外部服务是否启动正常。"], empty_summary="当前没有可用的机器链路信息。", ok_summary="已记录机器链路信息。"),
            "material": _quality_section("料", [], ["先确认 Markdown、检索结果和地点数据是否齐备。"], empty_summary="当前没有可用的数据输入信息。", ok_summary="已记录数据输入信息。"),
            "method": _quality_section("法", [], ["先确认当前工作流步骤、修订轮次和 fallback 策略。"], empty_summary="当前没有可用的方法流程信息。", ok_summary="已记录方法流程信息。"),
            "environment": _quality_section("环", [], ["先检查网络、缓存和运行环境是否可用。"], empty_summary="当前没有可用的环境信息。", ok_summary="已记录环境信息。"),
            "measurement": _quality_section("测", [], ["先确认 trace、校验结果和 debug 输出是否完整。"], empty_summary="当前没有可用的测量信息。", ok_summary="已记录测量信息。"),
        }

    # ── 提取 state 原始数据 ──
    state = _runtime_state_from_source(source)
    reflection = build_runtime_reflection(source)
    pdca = build_runtime_pdca(source)
    trace = [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()]
    tool_traces = [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)]
    validation = dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {}
    feedback = [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)]
    degraded_reasons = [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()]
    memory_hits = {str(key): _safe_int(value) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()}
    memory_misses = {str(key): _safe_int(value) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()}
    revision_count = _safe_int(state.get("revision_count"))
    max_revisions = _safe_int(state.get("max_revisions"))
    llm_used = _safe_int(state.get("llm_calls_used"))
    llm_limit = _safe_int(state.get("llm_calls_limit"))

    # ── 1. 人（human）维度 ──
    human_findings: List[str] = ["Supervisor 负责本轮编排与收口。"]
    if trace:
        human_findings.append(f"已执行步骤：{' -> '.join(trace[:6])}")
    if feedback:
        human_findings.append(f"Critic 已给出 {len(feedback)} 条修订建议。")
    if bool(state.get("needs_revision")):
        human_findings.append("当前结果仍需要人工关注或继续修订。")
    human_actions = ["优先根据 Critic 建议和运行状态决定是否人工复核。"]
    if feedback:
        human_actions.append("先逐条处理 Critic 建议，再决定是否重新生成整稿。")
    if str(snapshot.get("error") or "").strip():
        human_actions.append("若连续失败，人工抽查源 Markdown 与人物资料输入。")

    # ── 2. 机（machine）维度 ──
    tool_summary = dict(reflection.get("tool_summary") or {})
    machine_findings: List[str] = []
    if tool_traces:
        machine_findings.append(f"本轮共调用 {int(tool_summary.get('total_calls') or 0)} 次工具。")
    if int(tool_summary.get("failed_calls") or 0) > 0:
        machine_findings.append(f"工具失败 {int(tool_summary.get('failed_calls') or 0)} 次。")
    if int(tool_summary.get("timed_out_calls") or 0) > 0:
        machine_findings.append(f"工具超时 {int(tool_summary.get('timed_out_calls') or 0)} 次。")
    if llm_limit > 0:
        machine_findings.append(f"LLM 预算使用 {llm_used}/{llm_limit}。")
    if bool(snapshot.get("used_legacy_fallback")):
        machine_findings.append("已启用 legacy fallback 收口。")
    machine_actions: List[str] = []
    if int(tool_summary.get("failed_calls") or 0) > 0 or int(tool_summary.get("timed_out_calls") or 0) > 0:
        machine_actions.append("优先定位失败/超时工具，再决定是否重试整条链路。")
    if llm_limit > 0 and llm_used >= max(1, llm_limit - 1):
        machine_actions.append("压缩低价值调用，优先保留检索、审稿和必要修订。")
    if not machine_actions:
        machine_actions.append("保持当前机器链路配置，继续观察长尾人物耗时。")

    # ── 3. 料（material）维度 ──
    material_findings: List[str] = []
    if list(state.get("plan") or []):
        material_findings.append(f"已记录计划项 {len(list(state.get('plan') or []))} 条。")
    if state.get("search_result"):
        material_findings.append("检索资料已写入 state.search_result。")
    if state.get("place_maps"):
        material_findings.append("地点映射结果已写入 state.place_maps。")
    if str(state.get("draft_markdown") or "").strip():
        material_findings.append("草稿 Markdown 已生成。")
    if validation:
        material_findings.append("校验结果已生成，可用于定位结构或事实问题。")
    if not material_findings:
        material_findings.append("当前只保留了轻量 runtime，未完整记录中间数据体。")
    material_actions: List[str] = []
    if not state.get("search_result"):
        material_actions.append("优先检查检索资料是否缺失，再判断后续问题。")
    if not state.get("place_maps") and any("map_agent" in item for item in trace):
        material_actions.append("检查地点映射是否写回 state.place_maps。")
    if not str(state.get("draft_markdown") or "").strip():
        material_actions.append("确认 EditorAgent 是否真正产出草稿 Markdown。")
    if not material_actions:
        material_actions.append('继续维持"Markdown/检索/地点"三类数据的单源一致性。')

    # ── 4. 法（method）维度 ──
    method_findings: List[str] = []
    if trace:
        method_findings.append(f"工作流主线：{' -> '.join(trace[:8])}")
    if revision_count > 0 or max_revisions > 0:
        method_findings.append(f"修订轮次 {revision_count}/{max_revisions}。")
    if degraded_reasons:
        method_findings.append(f"已记录降级原因：{'；'.join(degraded_reasons[:3])}")
    if str(snapshot.get("fallback") or "").strip():
        method_findings.append(f"fallback 策略：{str(snapshot.get('fallback') or '').strip()}")
    if pdca.get("status"):
        method_findings.append(f"PDCA 当前状态：{str(pdca.get('status') or '')}")
    method_actions: List[str] = []
    if revision_count > 0:
        method_actions.append("下一轮先按 Critic 反馈逐项修正，再决定是否重写全文。")
    if degraded_reasons:
        method_actions.append("优先修复降级节点，再恢复标准工作流。")
    if "finish_agent" not in trace and trace:
        method_actions.append("确认是否正常进入 FinishAgent，避免流程提前终止。")
    if not method_actions:
        method_actions.append("维持当前编排方法，继续按 PDCA 节奏稳定执行。")

    # ── 5. 环（environment）维度 ──
    environment_findings: List[str] = []
    environment_findings.append(f"LangGraph 可用：{'是' if bool(snapshot.get('langgraph_available')) else '否'}。")
    if memory_hits or memory_misses:
        environment_findings.append(
            f"缓存命中/未命中：{sum(memory_hits.values())}/{sum(memory_misses.values())}。"
        )
    if int(tool_summary.get("timed_out_calls") or 0) > 0:
        environment_findings.append("运行环境出现工具超时迹象。")
    if bool(snapshot.get("used_legacy_fallback")):
        environment_findings.append("环境或依赖波动已触发 fallback。")
    environment_actions: List[str] = []
    if int(tool_summary.get("timed_out_calls") or 0) > 0:
        environment_actions.append("检查外部 API、网络连通性和服务限流。")
    # 当 miss 数量超过 hit 时提示缓存问题
    if sum(memory_misses.values()) > sum(memory_hits.values()) and memory_misses:
        environment_actions.append("检查缓存预热与 TTL，减少重复冷启动。")
    if not environment_actions:
        environment_actions.append("当前环境面未见明显异常，继续保持运行基线。")

    # ── 6. 测（measurement）维度 ──
    measurement_findings: List[str] = []
    measurement_findings.append(f"execution_trace 记录 {len(trace)} 个步骤。")
    measurement_findings.append(f"tool_traces 记录 {len(tool_traces)} 次调用。")
    if validation:
        passed = "通过" if bool(validation.get("pass")) else "未通过"
        measurement_findings.append(f"校验结果：{passed}。")
    measurement_findings.append(f"runtime reflection 状态：{str(reflection.get('status') or '')}。")
    measurement_findings.append(f"PDCA 状态：{str(pdca.get('status') or '')}。")
    measurement_actions: List[str] = []
    if not tool_traces:
        measurement_actions.append("补齐 tool_traces，避免只能看到结果看不到过程。")
    if not validation:
        measurement_actions.append("补齐 validation 输出，避免无法区分生成错误与校验错误。")
    if not measurement_actions:
        measurement_actions.append("当前测量面基本齐备，可直接按人机料法环测排障。")

    framework_status = str(reflection.get("status") or "stable")
    return {
        "status": framework_status,
        "person": str(snapshot.get("person") or ""),
        "human": _quality_section("人", human_findings, human_actions, empty_summary="当前没有可用的人因信息。", ok_summary="已记录本轮负责人、人工介入点与修订责任。"),
        "machine": _quality_section("机", machine_findings, machine_actions, empty_summary="当前没有可用的机器链路信息。", ok_summary="已记录 LLM、工具调用与 fallback 状态。"),
        "material": _quality_section("料", material_findings, material_actions, empty_summary="当前没有可用的数据输入信息。", ok_summary="已记录输入资料、地点数据与草稿产物状态。"),
        "method": _quality_section("法", method_findings, method_actions, empty_summary="当前没有可用的方法流程信息。", ok_summary="已记录工作流、修订轮次与 fallback 策略。"),
        "environment": _quality_section("环", environment_findings, environment_actions, empty_summary="当前没有可用的环境信息。", ok_summary="已记录运行环境、缓存与依赖波动情况。"),
        "measurement": _quality_section("测", measurement_findings, measurement_actions, empty_summary="当前没有可用的测量信息。", ok_summary="已记录 trace、校验和调试观测面。"),
    }


# ══════════════════════════════════════════════════════════════════════
#  公开 API：运行时反思
# ══════════════════════════════════════════════════════════════════════


def build_runtime_reflection(source: object) -> StoryAgentRuntimeReflection:
    """基于运行时快照构建运行时反思（reflection）视图。

    综合分析 LLM 预算、工具调用、记忆命中、修订轮次和降级原因，生成：
    - strengths（已验证优势）
    - bottlenecks（当前瓶颈）
    - suggested_actions（下一步动作建议）
    - status（stable / watch / degraded）

    状态判定规则：
    - 有瓶颈但无降级/失败/超时 → watch
    - 有降级原因或工具失败/超时 → degraded
    - 无瓶颈 → stable
    - 空快照 → empty

    Args:
        source: 来源对象。

    Returns:
        StoryAgentRuntimeReflection，包含 strengths、bottlenecks、
        suggested_actions、llm_budget、retry_summary、tool_summary、
        memory_summary 等字段。
    """
    snapshot = normalize_runtime_snapshot(source)
    # ── 空快照处理 ──
    if not snapshot:
        return {
            "status": "empty",
            "strengths": [],
            "bottlenecks": [],
            "suggested_actions": ["当前没有可用的 runtime snapshot。"],
            "llm_budget": {"used": 0, "limit": 0, "utilization": 0.0, "near_limit": False},
            "retry_summary": {"revision_count": 0, "max_revisions": 0, "critic_passes": 0, "editor_passes": 0},
            "tool_summary": {"total_calls": 0, "failed_calls": 0, "timed_out_calls": 0, "success_rate": 0.0},
            "memory_summary": {"hit_count": 0, "miss_count": 0, "hit_buckets": [], "miss_buckets": []},
        }

    # ── 提取 state 原始数据 ──
    state = dict(snapshot.get("state") or {})
    trace = [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()]
    tool_traces = [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)]
    memory_hits = {str(key): _safe_int(value) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()}
    memory_misses = {str(key): _safe_int(value) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()}
    llm_used = _safe_int(state.get("llm_calls_used"))
    llm_limit = _safe_int(state.get("llm_calls_limit"))
    revision_count = _safe_int(state.get("revision_count"))
    max_revisions = _safe_int(state.get("max_revisions"))
    degraded_reasons = [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()]

    # ── 生成子摘要 ──
    tool_summary = _tool_summary(tool_traces)
    memory_summary = _memory_summary(memory_hits, memory_misses)
    utilization = 0.0 if llm_limit <= 0 else round(float(llm_used) / float(llm_limit), 4)
    llm_budget: RuntimeReflectionLlmBudget = {
        "used": llm_used,
        "limit": llm_limit,
        "utilization": utilization,
        # 接近上限：剩余调用次数 <= 1
        "near_limit": bool(llm_limit > 0 and llm_used >= max(1, llm_limit - 1)),
    }
    retry_summary: RuntimeReflectionRetrySummary = {
        "revision_count": revision_count,
        "max_revisions": max_revisions,
        "critic_passes": _trace_step_count(trace, "critic_agent"),
        "editor_passes": _trace_step_count(trace, "editor_agent"),
    }

    # ── 优势分析 ──
    strengths: List[str] = []
    if tool_summary["total_calls"] and tool_summary["failed_calls"] == 0:
        strengths.append("工具调用链路稳定")
    if memory_summary["hit_count"] > 0:
        strengths.append("长期记忆开始产生命中")
    if retry_summary["critic_passes"] > 0 and revision_count > 0:
        strengths.append("具备基于批评反馈的自修订能力")
    if (not degraded_reasons) and llm_limit > 0 and llm_used < llm_limit:
        strengths.append("LLM 预算仍有余量")

    # ── 瓶颈分析 ──
    bottlenecks: List[str] = []
    if degraded_reasons:
        bottlenecks.append(f"出现降级路径：{'、'.join(degraded_reasons[:3])}")
    if llm_budget["near_limit"]:
        bottlenecks.append("LLM 调用接近预算上限")
    if tool_summary["failed_calls"] > 0:
        bottlenecks.append(f"工具失败 {tool_summary['failed_calls']} 次")
    if tool_summary["timed_out_calls"] > 0:
        bottlenecks.append(f"工具超时 {tool_summary['timed_out_calls']} 次")
    if memory_summary["miss_count"] > memory_summary["hit_count"] and memory_summary["miss_count"] > 0:
        bottlenecks.append("记忆 miss 高于 hit，重复工作偏多")
    if revision_count > 0:
        bottlenecks.append(f"已触发 {revision_count} 轮修订")

    # ── 建议动作 ──
    suggested_actions: List[str] = []
    if degraded_reasons:
        suggested_actions.append("优先修复降级原因对应的节点，再扩写正文")
    if llm_budget["near_limit"]:
        suggested_actions.append("压缩低价值检索与重写步骤，优先处理高置信问题")
    if tool_summary["failed_calls"] > 0 or tool_summary["timed_out_calls"] > 0:
        suggested_actions.append("优先复用已成功工具结果，避免对失败工具重复重试")
    if memory_summary["miss_count"] > memory_summary["hit_count"] and memory_summary["miss_buckets"]:
        suggested_actions.append(f"将高频 miss 桶补入长期记忆：{'、'.join(memory_summary['miss_buckets'][:3])}")
    if revision_count > 0:
        suggested_actions.append("下一轮先按 Critic 反馈逐项修正，再生成完整稿")
    if not suggested_actions:
        suggested_actions.append("维持当前执行策略，继续按既定版式稳定产出")

    # ── 状态判定 ──
    status = "stable"
    if bottlenecks:
        status = "watch"
    if degraded_reasons or tool_summary["failed_calls"] > 0 or tool_summary["timed_out_calls"] > 0:
        status = "degraded"

    return {
        "status": status,
        "strengths": strengths,
        "bottlenecks": bottlenecks,
        "suggested_actions": suggested_actions,
        "llm_budget": llm_budget,
        "retry_summary": retry_summary,
        "tool_summary": tool_summary,
        "memory_summary": memory_summary,
    }


def build_runtime_reflection_prompt(source: object) -> str:
    """基于运行时反思构建可供 LLM 消费的文本提示。

    将 build_runtime_reflection 的结果格式化为多行文本，包含：
    当前状态、LLM 预算、修订轮次、记忆命中/未命中、优势、瓶颈、下一步动作。

    Args:
        source: 来源对象。

    Returns:
        格式化的运行时反思文本提示，每行一个要点。
    """
    reflection = build_runtime_reflection(source)
    strengths = [str(item) for item in list(reflection.get("strengths") or []) if str(item).strip()]
    bottlenecks = [str(item) for item in list(reflection.get("bottlenecks") or []) if str(item).strip()]
    actions = [str(item) for item in list(reflection.get("suggested_actions") or []) if str(item).strip()]
    llm_budget = dict(reflection.get("llm_budget") or {})
    retry_summary = dict(reflection.get("retry_summary") or {})
    memory_summary = dict(reflection.get("memory_summary") or {})
    lines = [
        "运行时反思：",
        f"- 当前状态：{str(reflection.get('status') or 'unknown')}",
        f"- LLM 预算：{int(llm_budget.get('used') or 0)}/{int(llm_budget.get('limit') or 0)}",
        f"- 修订轮次：{int(retry_summary.get('revision_count') or 0)}/{int(retry_summary.get('max_revisions') or 0)}",
        f"- 记忆命中/未命中：{int(memory_summary.get('hit_count') or 0)}/{int(memory_summary.get('miss_count') or 0)}",
    ]
    if strengths:
        lines.append(f"- 已验证优势：{'；'.join(strengths)}")
    if bottlenecks:
        lines.append(f"- 当前瓶颈：{'；'.join(bottlenecks)}")
    if actions:
        lines.append(f"- 下一步动作：{'；'.join(actions)}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  公开 API：聚合运行时元数据
# ══════════════════════════════════════════════════════════════════════


def aggregate_result_runtime_meta(results: List[Dict[str, object]]) -> AggregatedRuntimeMetadata:
    """跨多个人物聚合运行时元数据，生成 AggregatedRuntimeMetadata。

    遍历 results 列表中的每个人物结果，提取各自的运行时快照和元数据，
    累加 LLM 调用统计、降级原因、工具调用次数、记忆命中/未命中，
    并统计有运行时数据的人物数量、处于 watch/degraded 状态的人物数量。

    状态判定逻辑：
    - 若 result.status == "degraded" 或 runtime_status == "degraded"
      或 reflection_status == "degraded" → 计入 degraded_people_count。
    - 若 reflection_status == "watch" 且校验未通过 → 计入 watch_people_count。

    Args:
        results: 人物结果列表，每项为包含 person、status、_agent_runtime 等字段的 dict。

    Returns:
        通过 normalize_aggregated_runtime_meta 归一化后的 AggregatedRuntimeMetadata。
    """
    llm_calls_used = 0
    llm_calls_limit = 0
    degraded_reasons: List[str] = []
    execution_traces: Dict[str, List[str]] = {}
    tool_trace_count = 0
    used_legacy_fallback = False
    memory_hits: Dict[str, int] = {}
    memory_misses: Dict[str, int] = {}
    runtime_people_count = 0
    watch_people_count = 0
    degraded_people_count = 0

    for result in results:
        result_status = str(result.get("status") or "").strip()
        result_is_degraded = result_status == "degraded"
        # ── 提取该人物的运行时快照与元数据 ──
        runtime_snapshot = normalize_runtime_snapshot(result.get("_agent_runtime"))
        runtime = extract_agent_runtime_metadata(runtime_snapshot)

        # 无运行时数据的人物：仅当 result 本身标记为 degraded 时计入降级统计
        if not runtime.get("has_runtime"):
            if result_is_degraded:
                degraded_people_count += 1
            continue

        runtime_people_count += 1

        # ── 累加 LLM 调用统计 ──
        try:
            llm_calls_used += int(runtime.get("llm_calls_used") or 0)
        except Exception:
            pass
        try:
            llm_calls_limit += int(runtime.get("llm_calls_limit") or 0)
        except Exception:
            pass

        # ── 累加降级标记 ──
        used_legacy_fallback = used_legacy_fallback or bool(runtime.get("used_legacy_fallback"))
        for item in runtime.get("degraded_reasons") or []:
            reason = str(item or "").strip()
            if reason and reason not in degraded_reasons:
                degraded_reasons.append(reason)

        # ── 人物状态判定 ──
        reflection = build_runtime_reflection(runtime_snapshot)
        reflection_status = str(reflection.get("status") or "").strip()
        runtime_status = str(runtime.get("status") or "").strip()
        final_validation_clean = _final_validation_is_clean(result, runtime_snapshot)
        if result_is_degraded or runtime_status == "degraded" or reflection_status == "degraded":
            degraded_people_count += 1
        elif reflection_status == "watch" and not final_validation_clean:
            watch_people_count += 1

        # ── 记录执行追踪（按人物分组）──
        person = str(result.get("person") or runtime.get("person") or "").strip()
        trace = runtime.get("execution_trace") or []
        if person and isinstance(trace, list):
            execution_traces[person] = [str(item) for item in trace]

        # ── 累加工具调用次数 ──
        tool_traces = runtime.get("tool_traces") or []
        if isinstance(tool_traces, list):
            tool_trace_count += len(tool_traces)

        # ── 累加记忆桶统计 ──
        for bucket, count in dict(runtime.get("memory_hits") or {}).items():
            key = str(bucket or "").strip()
            if not key:
                continue
            memory_hits[key] = int(memory_hits.get(key) or 0) + int(count or 0)
        for bucket, count in dict(runtime.get("memory_misses") or {}).items():
            key = str(bucket or "").strip()
            if not key:
                continue
            memory_misses[key] = int(memory_misses.get(key) or 0) + int(count or 0)

    return normalize_aggregated_runtime_meta(
        {
            "llm_calls_used": llm_calls_used,
            "llm_calls_limit": llm_calls_limit,
            "degraded": bool(degraded_reasons) or degraded_people_count > 0,
            "degraded_reasons": degraded_reasons,
            "used_legacy_fallback": used_legacy_fallback,
            "execution_traces": execution_traces,
            "tool_trace_count": tool_trace_count,
            "runtime_people_count": runtime_people_count,
            "watch_people_count": watch_people_count,
            "degraded_people_count": degraded_people_count,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }
    )


# ══════════════════════════════════════════════════════════════════════
#  模块导出列表
# ══════════════════════════════════════════════════════════════════════

__all__ = [
    "RuntimePdcaSection",
    "RuntimeQualitySection",
    "RuntimeReflectionLlmBudget",
    "RuntimeReflectionMemorySummary",
    "RuntimeReflectionRetrySummary",
    "RuntimeReflectionToolSummary",
    "StoryAgentRuntimePdca",
    "StoryAgentRuntimeQualityFramework",
    "StoryAgentRuntimeReflection",
    "StoryAgentRuntimeSnapshot",
    "StoryAgentRuntimeStateSnapshot",
    "aggregate_result_runtime_meta",
    "build_runtime_quality_framework",
    "build_runtime_pdca",
    "build_runtime_reflection",
    "build_runtime_reflection_prompt",
    "build_runtime_snapshot",
    "extract_agent_runtime_metadata",
    "mark_runtime_legacy_fallback",
    "normalize_runtime_snapshot",
]
