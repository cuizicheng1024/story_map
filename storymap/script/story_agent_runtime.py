from __future__ import annotations

from typing import Dict, List, TypedDict

try:
    from .story_task_schema import AggregatedRuntimeMetadata, AgentRuntimeMetadata, normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta
except ImportError:
    from story_task_schema import AggregatedRuntimeMetadata, AgentRuntimeMetadata, normalize_agent_runtime_metadata, normalize_aggregated_runtime_meta


class StoryAgentRuntimeSnapshot(TypedDict, total=False):
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


class RuntimeReflectionLlmBudget(TypedDict, total=False):
    used: int
    limit: int
    utilization: float
    near_limit: bool


class RuntimeReflectionRetrySummary(TypedDict, total=False):
    revision_count: int
    max_revisions: int
    critic_passes: int
    editor_passes: int


class RuntimeReflectionToolSummary(TypedDict, total=False):
    total_calls: int
    failed_calls: int
    timed_out_calls: int
    success_rate: float


class RuntimeReflectionMemorySummary(TypedDict, total=False):
    hit_count: int
    miss_count: int
    hit_buckets: List[str]
    miss_buckets: List[str]


class StoryAgentRuntimeReflection(TypedDict, total=False):
    status: str
    strengths: List[str]
    bottlenecks: List[str]
    suggested_actions: List[str]
    llm_budget: RuntimeReflectionLlmBudget
    retry_summary: RuntimeReflectionRetrySummary
    tool_summary: RuntimeReflectionToolSummary
    memory_summary: RuntimeReflectionMemorySummary


class RuntimePdcaSection(TypedDict, total=False):
    summary: str
    items: List[str]


class StoryAgentRuntimePdca(TypedDict, total=False):
    status: str
    person: str
    plan: RuntimePdcaSection
    do: RuntimePdcaSection
    check: RuntimePdcaSection
    act: RuntimePdcaSection


class RuntimeQualitySection(TypedDict, total=False):
    label: str
    summary: str
    findings: List[str]
    repair_actions: List[str]


class StoryAgentRuntimeQualityFramework(TypedDict, total=False):
    status: str
    person: str
    human: RuntimeQualitySection
    machine: RuntimeQualitySection
    material: RuntimeQualitySection
    method: RuntimeQualitySection
    environment: RuntimeQualitySection
    measurement: RuntimeQualitySection


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _normalize_runtime_state_snapshot(source: object) -> StoryAgentRuntimeStateSnapshot:
    state = dict(source or {}) if isinstance(source, dict) else {}
    return {
        "llm_calls_used": _safe_int(state.get("llm_calls_used")),
        "llm_calls_limit": _safe_int(state.get("llm_calls_limit")),
        "revision_count": _safe_int(state.get("revision_count")),
        "max_revisions": _safe_int(state.get("max_revisions")),
        "needs_revision": bool(state.get("needs_revision")),
        "needs_redraft": bool(state.get("needs_redraft")),
        "degraded_reasons": [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()],
        "execution_trace": [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()],
        "tool_traces": [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)],
        "memory_hits": {str(key): _safe_int(value) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()},
        "memory_misses": {
            str(key): _safe_int(value) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()
        },
        "plan": [str(item) for item in list(state.get("plan") or []) if str(item).strip()],
        "search_result": dict(state.get("search_result") or {}) if isinstance(state.get("search_result"), dict) else {},
        "place_maps": [dict(item) for item in list(state.get("place_maps") or []) if isinstance(item, dict)],
        "draft_markdown": str(state.get("draft_markdown") or ""),
        "final_markdown": str(state.get("final_markdown") or ""),
        "validation": dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {},
        "critic_feedback": [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)],
    }


def _runtime_snapshot_from(source: object) -> StoryAgentRuntimeSnapshot:
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


def normalize_runtime_snapshot(source: object) -> StoryAgentRuntimeSnapshot:
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict) or not runtime:
        return {}
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
    return _runtime_snapshot_from(runtime)


def build_runtime_snapshot(
    person: str,
    result: object = None,
    *,
    fallback: str = "",
    error: str = "",
) -> StoryAgentRuntimeSnapshot:
    snapshot = normalize_runtime_snapshot(result)
    snapshot["person"] = str(person or "")
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


def mark_runtime_legacy_fallback(runtime: object, *, person: str, markdown: object) -> StoryAgentRuntimeSnapshot:
    snapshot = normalize_runtime_snapshot(runtime)
    snapshot["person"] = str(snapshot.get("person") or person or "")
    snapshot["used_legacy_fallback"] = True
    snapshot["legacy_markdown_ok"] = bool(str(markdown or "").strip())
    return snapshot


def extract_agent_runtime_metadata(source: object) -> AgentRuntimeMetadata:
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


def _trace_step_count(trace: List[str], name: str) -> int:
    return sum(1 for item in trace if str(item or "").strip() == name)


def _tool_summary(tool_traces: List[Dict[str, object]]) -> RuntimeReflectionToolSummary:
    total_calls = len(tool_traces)
    failed_calls = sum(1 for item in tool_traces if isinstance(item, dict) and not bool(item.get("success", True)))
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
    return {
        "hit_count": sum(int(value or 0) for value in memory_hits.values()),
        "miss_count": sum(int(value or 0) for value in memory_misses.values()),
        "hit_buckets": [str(key) for key, value in memory_hits.items() if int(value or 0) > 0],
        "miss_buckets": [str(key) for key, value in memory_misses.items() if int(value or 0) > 0],
    }


def _final_validation_is_clean(result: Dict[str, object], runtime_snapshot: StoryAgentRuntimeSnapshot) -> bool:
    validation = result.get("_validation")
    if not isinstance(validation, dict):
        state = dict(runtime_snapshot.get("state") or {})
        validation = state.get("validation")
    if not isinstance(validation, dict) or not validation:
        return False
    return bool(validation.get("pass"))


def _runtime_state_from_source(source: object) -> Dict[str, object]:
    runtime = getattr(source, "last_agent_runtime", source)
    if not isinstance(runtime, dict) or not runtime:
        return {}
    if isinstance(runtime.get("state"), dict):
        return dict(runtime.get("state") or {})
    return dict(runtime)


def _pdca_summary(items: List[str], empty_summary: str, ok_summary: str) -> str:
    return ok_summary if items else empty_summary


def _quality_section(label: str, findings: List[str], repair_actions: List[str], *, empty_summary: str, ok_summary: str) -> RuntimeQualitySection:
    cleaned_findings = [str(item) for item in findings if str(item).strip()]
    cleaned_actions = [str(item) for item in repair_actions if str(item).strip()]
    return {
        "label": label,
        "summary": ok_summary if cleaned_findings else empty_summary,
        "findings": cleaned_findings,
        "repair_actions": cleaned_actions,
    }


def build_runtime_pdca(source: object) -> StoryAgentRuntimePdca:
    snapshot = normalize_runtime_snapshot(source)
    if not snapshot:
        return {
            "status": "empty",
            "person": "",
            "plan": {"summary": "当前没有可用的执行计划。", "items": []},
            "do": {"summary": "当前没有可用的执行动作。", "items": []},
            "check": {"summary": "当前没有可用的检查结果。", "items": []},
            "act": {"summary": "当前没有可用的处置动作。", "items": []},
        }
    state = _runtime_state_from_source(source)
    trace = [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()]
    tool_traces = [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)]
    validation = dict(state.get("validation") or {}) if isinstance(state.get("validation"), dict) else {}
    feedback = [dict(item) for item in list(state.get("critic_feedback") or []) if isinstance(item, dict)]
    degraded_reasons = [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()]
    revision_count = _safe_int(state.get("revision_count"))
    max_revisions = _safe_int(state.get("max_revisions"))

    plan_items = [str(item) for item in list(state.get("plan") or []) if str(item).strip()]
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

    do_items: List[str] = []
    for item in tool_traces:
        tool_name = str(item.get("tool_name") or "").strip() or "unknown_tool"
        agent_step = str(item.get("agent_step") or "").strip() or "unknown_agent"
        success = "成功" if bool(item.get("success", True)) else "失败"
        duration_ms = _safe_int(item.get("duration_ms"))
        do_items.append(f"{agent_step} 调用 {tool_name}，{success}，{duration_ms}ms")
    if not do_items and trace:
        do_items = [f"执行步骤：{item}" for item in trace]

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


def build_runtime_quality_framework(source: object) -> StoryAgentRuntimeQualityFramework:
    snapshot = normalize_runtime_snapshot(source)
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
        material_actions.append("继续维持“Markdown/检索/地点”三类数据的单源一致性。")

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
    if sum(memory_misses.values()) > sum(memory_hits.values()) and memory_misses:
        environment_actions.append("检查缓存预热与 TTL，减少重复冷启动。")
    if not environment_actions:
        environment_actions.append("当前环境面未见明显异常，继续保持运行基线。")

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


def build_runtime_reflection(source: object) -> StoryAgentRuntimeReflection:
    snapshot = normalize_runtime_snapshot(source)
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

    tool_summary = _tool_summary(tool_traces)
    memory_summary = _memory_summary(memory_hits, memory_misses)
    utilization = 0.0 if llm_limit <= 0 else round(float(llm_used) / float(llm_limit), 4)
    llm_budget: RuntimeReflectionLlmBudget = {
        "used": llm_used,
        "limit": llm_limit,
        "utilization": utilization,
        "near_limit": bool(llm_limit > 0 and llm_used >= max(1, llm_limit - 1)),
    }
    retry_summary: RuntimeReflectionRetrySummary = {
        "revision_count": revision_count,
        "max_revisions": max_revisions,
        "critic_passes": _trace_step_count(trace, "critic_agent"),
        "editor_passes": _trace_step_count(trace, "editor_agent"),
    }

    strengths: List[str] = []
    if tool_summary["total_calls"] and tool_summary["failed_calls"] == 0:
        strengths.append("工具调用链路稳定")
    if memory_summary["hit_count"] > 0:
        strengths.append("长期记忆开始产生命中")
    if retry_summary["critic_passes"] > 0 and revision_count > 0:
        strengths.append("具备基于批评反馈的自修订能力")
    if (not degraded_reasons) and llm_limit > 0 and llm_used < llm_limit:
        strengths.append("LLM 预算仍有余量")

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


def aggregate_result_runtime_meta(results: List[Dict[str, object]]) -> AggregatedRuntimeMetadata:
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
        runtime_snapshot = normalize_runtime_snapshot(result.get("_agent_runtime"))
        runtime = extract_agent_runtime_metadata(runtime_snapshot)
        if not runtime.get("has_runtime"):
            if result_is_degraded:
                degraded_people_count += 1
            continue
        runtime_people_count += 1
        try:
            llm_calls_used += int(runtime.get("llm_calls_used") or 0)
        except Exception:
            pass
        try:
            llm_calls_limit += int(runtime.get("llm_calls_limit") or 0)
        except Exception:
            pass
        used_legacy_fallback = used_legacy_fallback or bool(runtime.get("used_legacy_fallback"))
        for item in runtime.get("degraded_reasons") or []:
            reason = str(item or "").strip()
            if reason and reason not in degraded_reasons:
                degraded_reasons.append(reason)
        reflection = build_runtime_reflection(runtime_snapshot)
        reflection_status = str(reflection.get("status") or "").strip()
        runtime_status = str(runtime.get("status") or "").strip()
        final_validation_clean = _final_validation_is_clean(result, runtime_snapshot)
        if result_is_degraded or runtime_status == "degraded" or reflection_status == "degraded":
            degraded_people_count += 1
        elif reflection_status == "watch" and not final_validation_clean:
            watch_people_count += 1
        person = str(result.get("person") or runtime.get("person") or "").strip()
        trace = runtime.get("execution_trace") or []
        if person and isinstance(trace, list):
            execution_traces[person] = [str(item) for item in trace]
        tool_traces = runtime.get("tool_traces") or []
        if isinstance(tool_traces, list):
            tool_trace_count += len(tool_traces)
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
