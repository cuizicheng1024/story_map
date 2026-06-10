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
    degraded_reasons: List[str]
    execution_trace: List[str]
    tool_traces: List[Dict[str, object]]
    memory_hits: Dict[str, int]
    memory_misses: Dict[str, int]


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
        "degraded_reasons": [str(item) for item in list(state.get("degraded_reasons") or []) if str(item).strip()],
        "execution_trace": [str(item) for item in list(state.get("execution_trace") or []) if str(item).strip()],
        "tool_traces": [dict(item) for item in list(state.get("tool_traces") or []) if isinstance(item, dict)],
        "memory_hits": {str(key): _safe_int(value) for key, value in dict(state.get("memory_hits") or {}).items() if str(key).strip()},
        "memory_misses": {
            str(key): _safe_int(value) for key, value in dict(state.get("memory_misses") or {}).items() if str(key).strip()
        },
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
            "degraded_reasons",
            "execution_trace",
            "tool_traces",
            "memory_hits",
            "memory_misses",
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
    degraded_people_count = 0
    for result in results:
        runtime = extract_agent_runtime_metadata(result.get("_agent_runtime"))
        if not runtime.get("has_runtime"):
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
        if str(runtime.get("status") or "").strip() == "degraded":
            degraded_people_count += 1
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
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "used_legacy_fallback": used_legacy_fallback,
        "execution_traces": execution_traces,
        "tool_trace_count": tool_trace_count,
        "runtime_people_count": runtime_people_count,
        "degraded_people_count": degraded_people_count,
        "memory_hits": memory_hits,
        "memory_misses": memory_misses,
        }
    )


__all__ = [
    "RuntimeReflectionLlmBudget",
    "RuntimeReflectionMemorySummary",
    "RuntimeReflectionRetrySummary",
    "RuntimeReflectionToolSummary",
    "StoryAgentRuntimeReflection",
    "StoryAgentRuntimeSnapshot",
    "StoryAgentRuntimeStateSnapshot",
    "aggregate_result_runtime_meta",
    "build_runtime_reflection",
    "build_runtime_reflection_prompt",
    "build_runtime_snapshot",
    "extract_agent_runtime_metadata",
    "mark_runtime_legacy_fallback",
    "normalize_runtime_snapshot",
]
