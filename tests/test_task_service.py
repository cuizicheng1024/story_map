import logging
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from task import TaskService


def _make_story_dir(tmp_path: Path, *names: str) -> Path:
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (story_dir / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    return story_dir


def _build_service(tmp_path: Path, **overrides) -> TaskService:
    _make_story_dir(tmp_path, "霍去病", "李白", "杜甫")
    defaults = {
        "logger": logging.getLogger("task-test"),
        "max_concurrency": 2,
        "color_palette": ("#111111", "#222222", "#333333"),
        "project_root": lambda: str(tmp_path),
        "format_seconds": lambda sec: f"{sec:.2f}s",
        "validate_input_text": lambda text: None if str(text).strip() else "empty",
        "get_llm_client": lambda **_kwargs: object(),
        "extract_historical_figures": lambda _client, _text: [],
        "generate_for_person": lambda _client, person, **_kwargs: {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        },
        "ensure_profile_exports": lambda _profile, person, **_kwargs: {
            "geojson": f"/tmp/{person}.geojson",
            "csv": f"/tmp/{person}.csv",
        },
        "ensure_multi_exports": lambda _people, base_name, **_kwargs: {
            "geojson": f"/tmp/{base_name}.geojson",
            "csv": f"/tmp/{base_name}.csv",
        },
        "compute_overlaps": lambda _people: [{"name": "西安", "count": 2}],
        "build_conclusion": lambda results, multi: f"{'multi' if multi else 'single'}:{len(results)}",
        "render_multi_html": lambda data: f"<html>{data['title']}</html>",
        "save_html": lambda name, _html: f"/tmp/{name}.html",
        "relative_path": lambda path: path.replace("/tmp/", ""),
        "task_ttl_seconds": 60,
        "max_tasks": 50,
    }
    defaults.update(overrides)
    return TaskService(**defaults)


def _wait_for_task(service: TaskService, task_id: str, *, timeout: float = 2.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        snapshot = service.snapshot_task(task_id)
        if snapshot.get("status") in {"completed", "failed"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish in time")


def test_task_service_cleans_up_expired_finished_tasks(tmp_path):
    service = _build_service(tmp_path, task_ttl_seconds=60, max_tasks=50)
    try:
        task_id = service._create_task("old")
        service._update_task(task_id, status="completed")
        service._tasks[task_id]["updated_at"] = time.time() - 120

        fresh = service.submit_task("霍去病")

        assert fresh["ok"] is True
        assert service.snapshot_task(task_id)["ok"] is False
    finally:
        service.shutdown()


def test_task_service_marks_task_failed_when_generation_crashes(tmp_path):
    def _boom(_client, person, **_kwargs):
        raise RuntimeError(f"{person} boom")

    service = _build_service(tmp_path, generate_for_person=_boom)
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "failed"
        assert "霍去病 boom" in snapshot["error"]
        labels = [event["label"] for event in snapshot["progress"]]
        assert labels[-2:] == ["失败", "完成"]
    finally:
        service.shutdown()


def test_task_service_builds_multi_person_summary(tmp_path):
    service = _build_service(tmp_path)
    try:
        submit = service.submit_task("李白 杜甫")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "completed"
        result = snapshot["result"]
        assert result["people"] == ["李白", "杜甫"]
        assert result["multi_html_path"].endswith(".html")
        assert result["multi"]["geojson"].endswith(".geojson")
        assert result["overlaps"] == [{"name": "西安", "count": 2}]
        assert len(result["files"]) == 2
    finally:
        service.shutdown()


def test_task_service_recovers_completed_task_from_disk(tmp_path):
    service = _build_service(tmp_path)
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])
        assert snapshot["status"] == "completed"
    finally:
        service.shutdown()

    restored = _build_service(tmp_path)
    try:
        recovered = restored.snapshot_task(submit["task_id"])
        assert recovered["ok"] is True
        assert recovered["status"] == "completed"
        assert recovered["result"]["people"] == ["霍去病"]
    finally:
        restored.shutdown()


def test_task_service_marks_inflight_tasks_failed_after_restart(tmp_path):
    service = _build_service(tmp_path)
    try:
        task_id = service._create_task("霍去病")
        service._update_task(task_id, status="running")
    finally:
        service.shutdown()

    restored = _build_service(tmp_path)
    try:
        snapshot = restored.snapshot_task(task_id)
        assert snapshot["ok"] is True
        assert snapshot["status"] == "failed"
        assert "服务重启导致任务中断" in snapshot["error"]
        labels = [event["label"] for event in snapshot["progress"]]
        assert labels[-1] == "中断"
    finally:
        restored.shutdown()
