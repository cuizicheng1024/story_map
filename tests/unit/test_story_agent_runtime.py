
from storymap.script.runtime.legacy_agent import runtime as story_agent_runtime

def test_build_runtime_snapshot_and_extract_metadata():
    snapshot = story_agent_runtime.build_runtime_snapshot(
        "李白",
        {
            "max_llm_calls": 4,
            "langgraph_available": True,
            "tool_specs": [{"name": "search_person_info"}],
            "state": {
                "llm_calls_used": 2,
                "llm_calls_limit": 4,
                "degraded_reasons": ["editor_fallback"],
                "execution_trace": ["supervisor", "search_agent"],
                "tool_traces": [{"tool_name": "search_person_info"}],
                "memory_hits": {"search": 1},
                "memory_misses": {"place_map": 1},
            },
        },
    )

    assert snapshot["person"] == "李白"
    assert snapshot["state"]["llm_calls_used"] == 2
    assert snapshot["state"]["revision_count"] == 0

    metadata = story_agent_runtime.extract_agent_runtime_metadata(snapshot)

    assert metadata == {
        "has_runtime": True,
        "status": "degraded",
        "status_info": {
            "code": "degraded",
            "label": "已降级",
            "level": "warning",
            "hint": "降级原因：editor_fallback",
        },
        "person": "李白",
        "langgraph_available": True,
        "used_legacy_fallback": False,
        "legacy_markdown_ok": False,
        "fallback": "",
        "error": "",
        "max_llm_calls": 4,
        "tool_specs": [{"name": "search_person_info"}],
        "llm_calls_used": 2,
        "llm_calls_limit": 4,
        "degraded_reasons": ["editor_fallback"],
        "execution_trace": ["supervisor", "search_agent"],
        "tool_traces": [{"tool_name": "search_person_info"}],
        "memory_hits": {"search": 1},
        "memory_misses": {"place_map": 1},
    }

def test_mark_runtime_legacy_fallback_preserves_existing_snapshot():
    marked = story_agent_runtime.mark_runtime_legacy_fallback(
        {
            "person": "李白",
            "max_llm_calls": 4,
            "tool_specs": [{"name": "search_person_info"}],
            "state": {"llm_calls_used": 1},
        },
        person="李白",
        markdown="# 李白\n",
    )

    assert marked["used_legacy_fallback"] is True
    assert marked["legacy_markdown_ok"] is True
    assert marked["tool_specs"] == [{"name": "search_person_info"}]
    assert marked["state"]["llm_calls_used"] == 1
    assert marked["state"]["llm_calls_limit"] == 0
    assert marked["state"]["revision_count"] == 0
    assert marked["state"]["max_revisions"] == 0
    assert marked["state"]["degraded_reasons"] == []
    assert marked["state"]["execution_trace"] == []
    assert marked["state"]["tool_traces"] == []
    assert marked["state"]["memory_hits"] == {}
    assert marked["state"]["memory_misses"] == {}
    assert marked["state"]["validation"] == {}
    assert marked["state"]["critic_feedback"] == []

def test_build_runtime_snapshot_preserves_fields_needed_by_pdca_and_quality_views():
    snapshot = story_agent_runtime.build_runtime_snapshot(
        "李白",
        {
            "state": {
                "plan": ["SearchAgent 检索人物资料"],
                "search_result": {"person": "李白"},
                "place_maps": [{"query": "碎叶城", "lat": 1.0, "lng": 2.0}],
                "draft_markdown": "# 李白\n",
                "validation": {"pass": False, "risk_level": "high"},
                "critic_feedback": [{"field": "location", "claim": "碎叶城"}],
                "needs_revision": True,
                "llm_calls_used": 1,
                "llm_calls_limit": 4,
                "execution_trace": ["supervisor", "critic_agent"],
                "tool_traces": [],
            }
        },
    )

    assert snapshot["state"]["plan"] == ["SearchAgent 检索人物资料"]
    assert snapshot["state"]["search_result"] == {"person": "李白"}
    assert snapshot["state"]["place_maps"] == [{"query": "碎叶城", "lat": 1.0, "lng": 2.0}]
    assert snapshot["state"]["draft_markdown"] == "# 李白\n"
    assert snapshot["state"]["validation"] == {"pass": False, "risk_level": "high"}
    assert snapshot["state"]["critic_feedback"] == [{"field": "location", "claim": "碎叶城"}]
    assert snapshot["state"]["needs_revision"] is True

    pdca = story_agent_runtime.build_runtime_pdca(snapshot)
    framework = story_agent_runtime.build_runtime_quality_framework(snapshot)

    assert any("Critic 校验未通过" in item for item in pdca["check"]["items"])
    assert any("1 条修订建议" in item for item in pdca["check"]["items"])
    assert any("已记录计划项 1 条。" == item for item in framework["material"]["findings"])
    assert any("草稿 Markdown 已生成。" == item for item in framework["material"]["findings"])

def test_normalize_runtime_snapshot_upgrades_flattened_runtime_fields():
    snapshot = story_agent_runtime.normalize_runtime_snapshot(
        {
            "person": "杜甫",
            "max_llm_calls": 4,
            "tool_specs": [{"name": "search_person_info"}],
            "llm_calls_used": 1,
            "llm_calls_limit": 4,
            "degraded_reasons": ["search_fallback"],
            "execution_trace": ["supervisor", "editor_agent"],
            "tool_traces": [{"tool_name": "search_person_info"}],
            "memory_hits": {"search": 2},
            "memory_misses": {"place_map": 1},
            "used_legacy_fallback": True,
        }
    )

    assert snapshot["person"] == "杜甫"
    assert snapshot["used_legacy_fallback"] is True
    assert snapshot["state"]["llm_calls_used"] == 1
    assert snapshot["state"]["llm_calls_limit"] == 4
    assert snapshot["state"]["revision_count"] == 0
    assert snapshot["state"]["max_revisions"] == 0
    assert snapshot["state"]["degraded_reasons"] == ["search_fallback"]
    assert snapshot["state"]["execution_trace"] == ["supervisor", "editor_agent"]
    assert snapshot["state"]["tool_traces"] == [{"tool_name": "search_person_info"}]
    assert snapshot["state"]["memory_hits"] == {"search": 2}
    assert snapshot["state"]["memory_misses"] == {"place_map": 1}
    assert snapshot["state"]["validation"] == {}
    assert snapshot["state"]["critic_feedback"] == []

def test_normalize_runtime_snapshot_keeps_new_flattened_runtime_fields():
    snapshot = story_agent_runtime.normalize_runtime_snapshot(
        {
            "person": "李清照",
            "plan": ["SearchAgent 检索人物资料"],
            "search_result": {"person": "李清照"},
            "place_maps": [{"query": "济南", "lat": 36.67, "lng": 117.0}],
            "draft_markdown": "# 李清照\n",
            "final_markdown": "# 李清照\n\n定稿",
            "validation": {"pass": False, "risk_level": "medium"},
            "critic_feedback": [{"field": "timeline", "claim": "南渡"}],
            "needs_revision": True,
            "needs_redraft": False,
        }
    )

    assert snapshot["person"] == "李清照"
    assert snapshot["state"]["plan"] == ["SearchAgent 检索人物资料"]
    assert snapshot["state"]["search_result"] == {"person": "李清照"}
    assert snapshot["state"]["place_maps"] == [{"query": "济南", "lat": 36.67, "lng": 117.0}]
    assert snapshot["state"]["draft_markdown"] == "# 李清照\n"
    assert snapshot["state"]["final_markdown"] == "# 李清照\n\n定稿"
    assert snapshot["state"]["validation"] == {"pass": False, "risk_level": "medium"}
    assert snapshot["state"]["critic_feedback"] == [{"field": "timeline", "claim": "南渡"}]
    assert snapshot["state"]["needs_revision"] is True
    assert snapshot["state"]["needs_redraft"] is False

def test_aggregate_result_runtime_meta_supports_snapshot_and_flattened_runtime():
    meta = story_agent_runtime.aggregate_result_runtime_meta(
        [
            {
                "person": "李白",
                "_agent_runtime": {
                    "person": "李白",
                    "state": {
                        "llm_calls_used": 2,
                        "llm_calls_limit": 4,
                        "degraded_reasons": ["search_fallback"],
                        "execution_trace": ["supervisor", "search_agent"],
                        "tool_traces": [{"tool_name": "search_person_info"}],
                        "memory_hits": {"search": 1},
                        "memory_misses": {"place_map": 1},
                    },
                },
            },
            {
                "person": "杜甫",
                "_agent_runtime": {
                    "person": "杜甫",
                    "llm_calls_used": 1,
                    "llm_calls_limit": 4,
                    "degraded_reasons": [],
                    "execution_trace": ["supervisor", "editor_agent"],
                    "tool_traces": [{"tool_name": "generate_markdown"}, {"tool_name": "validate_markdown"}],
                    "used_legacy_fallback": True,
                    "memory_hits": {"search": 2},
                    "memory_misses": {},
                },
            },
        ]
    )

    assert meta["llm_calls_used"] == 3
    assert meta["llm_calls_limit"] == 8
    assert meta["degraded"] is True
    assert meta["degraded_reasons"] == ["search_fallback"]
    assert meta["execution_traces"]["李白"] == ["supervisor", "search_agent"]
    assert meta["execution_traces"]["杜甫"] == ["supervisor", "editor_agent"]
    assert meta["tool_trace_count"] == 3
    assert meta["used_legacy_fallback"] is True
    assert meta["has_runtime"] is True
    assert meta["status"] == "degraded"
    assert meta["runtime_people_count"] == 2
    assert meta["degraded_people_count"] == 2
    assert meta["memory_hits"] == {"search": 3}
    assert meta["memory_misses"] == {"place_map": 1}

def test_aggregate_result_runtime_meta_marks_watch_when_people_need_attention():
    meta = story_agent_runtime.aggregate_result_runtime_meta(
        [
            {
                "person": "霍去病",
                "_agent_runtime": {
                    "person": "霍去病",
                    "state": {
                        "llm_calls_used": 1,
                        "llm_calls_limit": 4,
                        "revision_count": 1,
                        "max_revisions": 2,
                        "degraded_reasons": [],
                        "execution_trace": ["supervisor", "search_agent"],
                        "tool_traces": [{"tool_name": "search_person_info", "agent_step": "search_agent"}],
                        "memory_hits": {"search": 1},
                        "memory_misses": {"place_map": 1},
                    },
                },
            }
        ]
    )

    assert meta["has_runtime"] is True
    assert meta["status"] == "watch"
    assert meta["runtime_people_count"] == 1
    assert meta["watch_people_count"] == 1
    assert meta["degraded_people_count"] == 0
    assert meta["status_info"]["code"] == "watch"

def test_aggregate_result_runtime_meta_prefers_clean_final_validation_over_process_watch():
    meta = story_agent_runtime.aggregate_result_runtime_meta(
        [
            {
                "person": "霍去病",
                "_validation": {"pass": True, "issues": [], "metrics": {"coords": 3}},
                "_agent_runtime": {
                    "person": "霍去病",
                    "state": {
                        "llm_calls_used": 1,
                        "llm_calls_limit": 4,
                        "revision_count": 1,
                        "max_revisions": 2,
                        "degraded_reasons": [],
                        "execution_trace": ["supervisor", "search_agent"],
                        "tool_traces": [{"tool_name": "search_person_info", "agent_step": "search_agent"}],
                        "memory_hits": {"search": 1},
                        "memory_misses": {"place_map": 1},
                        "validation": {"pass": True, "issues": [], "metrics": {"coords": 3}},
                    },
                },
            }
        ]
    )

    assert meta["has_runtime"] is True
    assert meta["status"] == "ok"
    assert meta["runtime_people_count"] == 1
    assert meta["watch_people_count"] == 0
    assert meta["degraded_people_count"] == 0
    assert meta["status_info"]["code"] == "ok"

def test_aggregate_result_runtime_meta_preserves_result_level_degraded_signal():
    meta = story_agent_runtime.aggregate_result_runtime_meta(
        [
            {
                "person": "霍去病",
                "status": "degraded",
                "error": "render failed",
                "_agent_runtime": {
                    "person": "霍去病",
                    "state": {
                        "llm_calls_used": 1,
                        "llm_calls_limit": 4,
                        "degraded_reasons": [],
                        "execution_trace": ["supervisor", "search_agent"],
                        "tool_traces": [{"tool_name": "search_person_info", "agent_step": "search_agent"}],
                        "memory_hits": {"search": 1},
                        "memory_misses": {},
                    },
                },
            }
        ]
    )

    assert meta["has_runtime"] is True
    assert meta["status"] == "degraded"
    assert meta["runtime_people_count"] == 1
    assert meta["watch_people_count"] == 0
    assert meta["degraded_people_count"] == 1
    assert meta["status_info"]["code"] == "degraded"

def test_build_runtime_reflection_identifies_budget_memory_and_retry_risks():
    reflection = story_agent_runtime.build_runtime_reflection(
        {
            "person": "李白",
            "state": {
                "llm_calls_used": 3,
                "llm_calls_limit": 4,
                "revision_count": 1,
                "max_revisions": 2,
                "degraded_reasons": ["editor_agent:LLM_CALL_BUDGET_EXCEEDED:3/4"],
                "execution_trace": ["supervisor", "search_agent", "map_agent", "editor_agent", "critic_agent"],
                "tool_traces": [
                    {"tool_name": "search_person_info", "success": True},
                    {"tool_name": "generate_markdown", "success": False, "timed_out": True},
                ],
                "memory_hits": {"search": 1},
                "memory_misses": {"place_map": 2},
            },
        }
    )

    assert reflection["status"] == "degraded"
    assert reflection["llm_budget"]["near_limit"] is True
    assert reflection["retry_summary"]["revision_count"] == 1
    assert reflection["tool_summary"]["failed_calls"] == 1
    assert reflection["tool_summary"]["timed_out_calls"] == 1
    assert reflection["memory_summary"]["hit_count"] == 1
    assert reflection["memory_summary"]["miss_count"] == 2
    assert any("预算上限" in item for item in reflection["bottlenecks"])
    assert any("长期记忆" in item for item in reflection["suggested_actions"])

def test_build_runtime_pdca_maps_plan_do_check_act():
    pdca = story_agent_runtime.build_runtime_pdca(
        {
            "person": "李白",
            "state": {
                "plan": ["SearchAgent 检索人物资料", "CriticAgent 做一致性检查"],
                "llm_calls_limit": 4,
                "revision_count": 1,
                "max_revisions": 2,
                "needs_revision": True,
                "validation": {"pass": False, "risk_level": "medium"},
                "critic_feedback": [{"field": "location", "reason": "地点不够精确"}],
                "degraded_reasons": ["map_agent:timeout"],
                "execution_trace": ["supervisor", "search_agent", "critic_agent"],
                "tool_traces": [
                    {"tool_name": "search_person_info", "agent_step": "search_agent", "success": True, "duration_ms": 12}
                ],
            },
        }
    )

    assert pdca["person"] == "李白"
    assert "LLM 预算上限 4 次" in pdca["plan"]["items"]
    assert pdca["do"]["items"] == ["search_agent 调用 search_person_info，成功，12ms"]
    assert any("Critic 校验未通过" in item for item in pdca["check"]["items"])
    assert any("1 条修订建议" in item for item in pdca["check"]["items"])
    assert any("修订轮次 1/2" == item for item in pdca["act"]["items"])
    assert any("进入下一轮修订" == item for item in pdca["act"]["items"])

def test_build_runtime_quality_framework_maps_6m_root_cause_view():
    framework = story_agent_runtime.build_runtime_quality_framework(
        {
            "person": "李白",
            "langgraph_available": True,
            "state": {
                "plan": ["SearchAgent 检索人物资料"],
                "llm_calls_used": 3,
                "llm_calls_limit": 4,
                "revision_count": 1,
                "max_revisions": 2,
                "needs_revision": True,
                "search_result": {"person": "李白"},
                "draft_markdown": "# 李白",
                "validation": {"pass": False, "risk_level": "medium"},
                "critic_feedback": [{"field": "timeline", "reason": "年代不清"}],
                "degraded_reasons": ["map_agent:timeout"],
                "execution_trace": ["supervisor", "search_agent", "critic_agent"],
                "tool_traces": [
                    {"tool_name": "search_person_info", "agent_step": "search_agent", "success": True, "duration_ms": 12},
                    {"tool_name": "fetch_ancient_place_map", "agent_step": "map_agent", "success": False, "timed_out": True, "duration_ms": 8000},
                ],
                "memory_hits": {"search": 1},
                "memory_misses": {"place_map": 2},
            },
        }
    )

    assert framework["person"] == "李白"
    assert framework["human"]["label"] == "人"
    assert any("Critic 已给出 1 条修订建议。" == item for item in framework["human"]["findings"])
    assert framework["machine"]["label"] == "机"
    assert any("工具超时 1 次。" == item for item in framework["machine"]["findings"])
    assert framework["material"]["label"] == "料"
    assert any("草稿 Markdown 已生成。" == item for item in framework["material"]["findings"])
    assert framework["method"]["label"] == "法"
    assert any("修订轮次 1/2。" == item for item in framework["method"]["findings"])
    assert framework["environment"]["label"] == "环"
    assert any("缓存命中/未命中：1/2。" == item for item in framework["environment"]["findings"])
    assert framework["measurement"]["label"] == "测"
    assert any("tool_traces 记录 2 次调用。" == item for item in framework["measurement"]["findings"])

def test_empty_runtime_snapshot_and_reflection_stay_empty():
    assert story_agent_runtime.normalize_runtime_snapshot(None) == {}

    reflection = story_agent_runtime.build_runtime_reflection(None)
    pdca = story_agent_runtime.build_runtime_pdca(None)
    framework = story_agent_runtime.build_runtime_quality_framework(None)

    assert reflection["status"] == "empty"
    assert reflection["tool_summary"]["total_calls"] == 0
    assert reflection["suggested_actions"] == ["当前没有可用的 runtime snapshot。"]
    assert pdca["status"] == "empty"
    assert pdca["plan"]["items"] == []
    assert framework["status"] == "empty"
    assert framework["measurement"]["label"] == "测"
