import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_agent_runtime


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
    assert marked["state"] == {
        "llm_calls_used": 1,
        "llm_calls_limit": 0,
        "revision_count": 0,
        "max_revisions": 0,
        "degraded_reasons": [],
        "execution_trace": [],
        "tool_traces": [],
        "memory_hits": {},
        "memory_misses": {},
    }


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
    assert snapshot["state"] == {
        "llm_calls_used": 1,
        "llm_calls_limit": 4,
        "revision_count": 0,
        "max_revisions": 0,
        "degraded_reasons": ["search_fallback"],
        "execution_trace": ["supervisor", "editor_agent"],
        "tool_traces": [{"tool_name": "search_person_info"}],
        "memory_hits": {"search": 2},
        "memory_misses": {"place_map": 1},
    }


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
