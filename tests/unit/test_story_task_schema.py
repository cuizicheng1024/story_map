import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_task_schema


def test_normalize_task_result_summary_preserves_degraded_success_when_status_is_missing():
    summary = story_task_schema.normalize_task_result_summary(
        {
            "ok": False,
            "people": ["霍去病"],
            "results": [
                {
                    "ok": False,
                    "status": "degraded",
                    "person": "霍去病",
                    "error": "render failed",
                }
            ],
        }
    )

    assert summary["success_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["status"] == "completed"
    assert summary["status_info"]["code"] == "completed"


def test_build_task_list_item_prefers_runtime_warning_for_completed_task():
    item = story_task_schema.build_task_list_item(
        {
            "id": "task-1",
            "text": "霍去病",
            "status": "completed",
            "created_at": 1,
            "updated_at": 2,
            "error": "",
            "result": {
                "ok": True,
                "status": "completed",
                "people": ["霍去病"],
                "results": [{"ok": True, "person": "霍去病"}],
                "success_count": 1,
                "failed_count": 0,
                "failed_people": [],
                "meta": {
                    "runtime_people_count": 1,
                    "watch_people_count": 1,
                    "degraded_people_count": 0,
                },
            },
        }
    )

    assert item["status"] == "completed"
    assert item["status_info"]["code"] == "watch"
    assert item["status_info"]["level"] == "warning"
