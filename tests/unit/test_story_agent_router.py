import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_agent_router


def test_supervisor_prefers_editor_on_revision_when_budget_is_near_limit():
    update = story_agent_router.build_supervisor_update(
        {
            "search_result": {"person": "李白"},
            "place_maps": [{"query": "碎叶城"}],
            "draft_markdown": "# draft",
            "validation": {"pass": False},
            "critic_feedback": [
                {
                    "field": "location",
                    "claim": "碎叶城",
                    "correction": "碎叶城（今吉尔吉斯斯坦托克马克）",
                }
            ],
            "needs_revision": True,
            "llm_calls_used": 3,
            "llm_calls_limit": 4,
            "execution_trace": ["supervisor", "search_agent", "map_agent", "editor_agent", "critic_agent"],
            "tool_traces": [{"tool_name": "search_person_info", "success": True}],
        }
    )

    assert update["next_step"] == "editor_agent"


def test_supervisor_prefers_editor_when_tools_are_unstable_during_revision():
    update = story_agent_router.build_supervisor_update(
        {
            "search_result": {"person": "李白"},
            "place_maps": [],
            "draft_markdown": "# draft",
            "validation": {"pass": False},
            "critic_feedback": [{"field": "other", "claim": "表述偏弱"}],
            "needs_revision": True,
            "llm_calls_used": 1,
            "llm_calls_limit": 4,
            "execution_trace": ["supervisor", "search_agent", "editor_agent", "critic_agent"],
            "tool_traces": [
                {
                    "tool_name": "generate_markdown",
                    "agent_step": "editor_agent",
                    "success": False,
                    "timed_out": True,
                }
            ],
        }
    )

    assert update["next_step"] == "finish_agent"


def test_supervisor_does_not_retry_map_when_location_feedback_coexists_with_failed_map_call():
    update = story_agent_router.build_supervisor_update(
        {
            "search_result": {"person": "李白"},
            "place_maps": [],
            "draft_markdown": "# draft",
            "validation": {"pass": False},
            "critic_feedback": [{"field": "location", "claim": "碎叶城"}],
            "needs_revision": True,
            "llm_calls_used": 1,
            "llm_calls_limit": 4,
            "execution_trace": ["supervisor", "search_agent", "map_agent", "editor_agent", "critic_agent"],
            "tool_traces": [{"tool_name": "fetch_ancient_place_map", "success": False, "timed_out": True}],
        }
    )

    assert update["next_step"] == "editor_agent"


def test_supervisor_prefers_editor_when_memory_miss_is_high_on_revision():
    update = story_agent_router.build_supervisor_update(
        {
            "search_result": {"person": "李白"},
            "place_maps": [],
            "draft_markdown": "# draft",
            "validation": {"pass": False},
            "critic_feedback": [{"field": "other", "claim": "补充史料"}],
            "needs_revision": True,
            "llm_calls_used": 1,
            "llm_calls_limit": 6,
            "execution_trace": ["supervisor", "search_agent", "editor_agent", "critic_agent"],
            "tool_traces": [{"tool_name": "search_person_info", "success": True}],
            "memory_hits": {"search": 1},
            "memory_misses": {"search": 3, "place_map": 1},
        }
    )

    assert update["next_step"] == "editor_agent"
