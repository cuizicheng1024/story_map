import logging
import json
import sys
import threading
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
        if snapshot.get("status") in {"completed", "failed", "partial_failed"}:
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


def test_task_service_marks_task_failed_when_all_people_return_errors(tmp_path):
    def _fail(_client, person, **_kwargs):
        return {"ok": False, "person": person, "error": f"{person} no data"}

    service = _build_service(tmp_path, generate_for_person=_fail)
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "failed"
        assert snapshot["result"]["ok"] is False
        assert snapshot["error"] == "霍去病 no data"
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


def test_task_service_marks_partial_failures_with_structured_status(tmp_path):
    def _generate(_client, person, **_kwargs):
        if person == "杜甫":
            return {"ok": False, "person": person, "error": "杜甫 no data"}
        return {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    service = _build_service(tmp_path, generate_for_person=_generate)
    try:
        submit = service.submit_task("李白 杜甫")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["exists"] is True
        assert snapshot["ok"] is False
        assert snapshot["status"] == "partial_failed"
        assert snapshot["status_info"]["code"] == "partial_failed"
        assert snapshot["status_info"]["level"] == "warning"
        assert "杜甫 no data" in snapshot["error"]
        assert snapshot["result"]["status"] == "partial_failed"
        assert snapshot["result"]["ok"] is False
        assert snapshot["result"]["status_info"]["code"] == "partial_failed"
        assert "成功 1 人，失败 1 人" in snapshot["result"]["status_info"]["hint"]
        assert snapshot["result"]["success_count"] == 1
        assert snapshot["result"]["failed_count"] == 1
        assert snapshot["result"]["failed_people"] == ["杜甫"]
    finally:
        service.shutdown()


def test_task_service_preserves_degraded_result_files(tmp_path):
    def _degraded(_client, person, **_kwargs):
        return {
            "ok": False,
            "status": "degraded",
            "degraded": True,
            "person": person,
            "error": "render failed",
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "fallback_html_path": f"/tmp/{person}.html",
            "_agent_runtime": {
                "person": person,
                "state": {
                    "llm_calls_used": 1,
                    "llm_calls_limit": 4,
                    "degraded_reasons": [],
                    "execution_trace": ["supervisor", "search_agent"],
                    "tool_traces": [
                        {
                            "tool_name": "search_person_info",
                            "agent_step": "search_agent",
                            "success": True,
                        }
                    ],
                    "memory_hits": {"search": 1},
                    "memory_misses": {},
                },
            },
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    service = _build_service(tmp_path, generate_for_person=_degraded)
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])
        debug_snapshot = service.task_debug_snapshot(submit["task_id"])

        assert snapshot["status"] == "completed"
        assert snapshot["ok"] is True
        assert snapshot["result"]["files"][0]["html"] == "霍去病.html"
        assert snapshot["result"]["results"][0]["status"] == "degraded"
        assert debug_snapshot["debug"]["result"]["ok"] is True
        assert debug_snapshot["debug"]["meta"]["status"] == "degraded"
        assert debug_snapshot["debug"]["ui"]["banner"]["code"] == "degraded"
        assert debug_snapshot["debug"]["people"][0]["ok"] is True
        assert debug_snapshot["debug"]["people"][0]["status_info"]["code"] == "degraded"
        assert debug_snapshot["debug"]["people"][0]["runtime"]["status"] == "ok"
    finally:
        service.shutdown()


def test_task_service_rebuilds_exports_after_profile_refresh(tmp_path):
    export_calls = []

    def _generate(_client, person, **_kwargs):
        return {
            "ok": True,
            "person": person,
            "cached": True,
            "refreshed": True,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    def _ensure_exports(_profile, person, *, allow_cache=True, **_kwargs):
        export_calls.append({"person": person, "allow_cache": allow_cache})
        return {
            "geojson": f"/tmp/{person}.geojson",
            "csv": f"/tmp/{person}.csv",
        }

    service = _build_service(tmp_path, generate_for_person=_generate, ensure_profile_exports=_ensure_exports)
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "completed"
        assert export_calls == [{"person": "霍去病", "allow_cache": False}]
    finally:
        service.shutdown()


def test_task_service_accepts_unknown_plain_person_name(tmp_path):
    service = _build_service(tmp_path)
    try:
        submit = service.submit_task("辛弃疾")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "completed"
        assert snapshot["result"]["people"] == ["辛弃疾"]
    finally:
        service.shutdown()


def test_task_service_accepts_authentic_person_extracted_by_llm(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pep_people_merged.json").write_text(
        json.dumps([{"name": "辛弃疾"}], ensure_ascii=False),
        encoding="utf-8",
    )

    service = _build_service(
        tmp_path,
        extract_historical_figures=lambda _client, _text: ["辛弃疾"],
    )
    try:
        submit = service.submit_task("请生成辛弃疾主页")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "completed"
        assert snapshot["result"]["people"] == ["辛弃疾"]
    finally:
        service.shutdown()


def test_task_service_blocks_non_authentic_story_people_before_generation(tmp_path):
    _make_story_dir(tmp_path, "奥楚蔑洛夫")
    (tmp_path / "storymap" / "examples" / "story" / "奥楚蔑洛夫.md").write_text(
        "# 奥楚蔑洛夫 文学虚构人物\n\n并非真实历史人物。\n",
        encoding="utf-8",
    )
    llm_calls = {"count": 0}

    def _get_llm_client(**_kwargs):
        llm_calls["count"] += 1
        return object()

    service = _build_service(tmp_path, get_llm_client=_get_llm_client)
    try:
        submit = service.submit_task("奥楚蔑洛夫")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "已拦截非真实或存疑人物：奥楚蔑洛夫"
        assert llm_calls["count"] == 1
    finally:
        service.shutdown()


def test_task_service_blocks_unknown_persons_extracted_by_llm(tmp_path):
    generated = []

    def _generate_for_person(_client, person, **_kwargs):
        generated.append(person)
        return {"ok": True, "person": person}

    service = _build_service(
        tmp_path,
        extract_historical_figures=lambda _client, _text: ["海绵宝宝"],
        generate_for_person=_generate_for_person,
    )
    try:
        submit = service.submit_task("请生成海绵宝宝主页")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "已拦截非真实或存疑人物：海绵宝宝"
        assert generated == []
    finally:
        service.shutdown()


def test_task_service_allows_explicit_single_person_input_not_in_registry(tmp_path):
    generated = []

    def _generate_for_person(_client, person, **_kwargs):
        generated.append(person)
        return {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    service = _build_service(
        tmp_path,
        extract_historical_figures=lambda _client, _text: ["岑参"],
        generate_for_person=_generate_for_person,
    )
    try:
        submit = service.submit_task("岑参")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "completed"
        assert snapshot["result"]["people"] == ["岑参"]
        assert generated == ["岑参"]
    finally:
        service.shutdown()


def test_task_service_marks_partially_blocked_targets_as_partial_failed(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pep_people_merged.json").write_text(
        json.dumps([{"name": "辛弃疾"}], ensure_ascii=False),
        encoding="utf-8",
    )

    service = _build_service(
        tmp_path,
        extract_historical_figures=lambda _client, _text: ["辛弃疾", "海绵宝宝"],
    )
    try:
        submit = service.submit_task("请生成辛弃疾和海绵宝宝主页")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "partial_failed"
        assert snapshot["error"] == "已拦截非真实或存疑人物：海绵宝宝"
        assert snapshot["result"]["people"] == ["辛弃疾", "海绵宝宝"]
        assert snapshot["result"]["success_count"] == 1
        assert snapshot["result"]["failed_count"] == 1
        assert snapshot["result"]["failed_people"] == ["海绵宝宝"]
        assert {item["person"] for item in snapshot["result"]["results"]} == {"辛弃疾", "海绵宝宝"}
        blocked = next(item for item in snapshot["result"]["results"] if item["person"] == "海绵宝宝")
        assert blocked["status"] == "failed"
        assert blocked["error"] == "已拦截非真实或存疑人物：海绵宝宝"
    finally:
        service.shutdown()


def test_task_service_rejects_question_like_input_when_no_person_found(tmp_path):
    service = _build_service(tmp_path)
    try:
        submit = service.submit_task("苏轼为何总在南方活动？")
        snapshot = _wait_for_task(service, submit["task_id"])

        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "未识别到人物，请输入人物姓名，或先进入人物页再提问。"
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
        assert recovered["exists"] is True
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
        assert snapshot["exists"] is True
        assert snapshot["ok"] is False
        assert snapshot["status"] == "failed"
        assert "服务重启导致任务中断" in snapshot["error"]
        labels = [event["label"] for event in snapshot["progress"]]
        assert labels[-1] == "中断"
    finally:
        restored.shutdown()


def test_task_service_migrates_legacy_json_state_into_sqlite(tmp_path):
    _make_story_dir(tmp_path, "霍去病")
    runtime_dir = tmp_path / "artifacts" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = runtime_dir / "task_state.json"
    legacy_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "legacy-task",
                        "text": "霍去病",
                        "status": "completed",
                        "created_at": time.time(),
                        "updated_at": time.time(),
                        "progress": [],
                        "result": {"ok": True, "people": ["霍去病"]},
                        "error": "",
                        "queue": {},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = _build_service(tmp_path)
    try:
        snapshot = service.snapshot_task("legacy-task")
        sqlite_path = tmp_path / "artifacts" / "runtime" / "task_state.sqlite3"

        assert snapshot["exists"] is True
        assert snapshot["ok"] is True
        assert snapshot["status"] == "completed"
        assert snapshot["result"]["people"] == ["霍去病"]
        assert sqlite_path.exists()
    finally:
        service.shutdown()


def test_task_service_exposes_debug_snapshot_and_storage_queries(tmp_path):
    service = _build_service(
        tmp_path,
        generate_for_person=lambda _client, person, **_kwargs: {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_agent_runtime": {
                "person": person,
                "state": {
                    "llm_calls_used": 1,
                    "llm_calls_limit": 4,
                    "revision_count": 1,
                    "max_revisions": 2,
                    "degraded_reasons": [],
                    "execution_trace": ["supervisor", "search_agent"],
                    "tool_traces": [
                        {
                            "tool_name": "search_person_info",
                            "agent_step": "search_agent",
                            "input_summary": "'霍去病'",
                            "output_summary": "{'person': '霍去病'}",
                        }
                    ],
                    "memory_hits": {"search": 1},
                    "memory_misses": {"place_map": 1},
                },
            },
            "_profile": {
                "person": {"name": person},
                "locations": [],
                "mapStyle": {},
            },
        },
    )
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])
        debug_snapshot = service.task_debug_snapshot(submit["task_id"])
        query_payload = service.list_tasks(limit=10)
        stats = service.storage_stats()
        maintain = service.maintain_storage(prune_expired=True, vacuum=False)

        assert snapshot["status"] == "completed"
        assert debug_snapshot["debug"]["meta"]["memory_hits"] == {"search": 1}
        assert debug_snapshot["debug"]["meta"]["status"] == "watch"
        assert debug_snapshot["debug"]["meta"]["status_info"]["code"] == "watch"
        assert debug_snapshot["debug"]["result"]["status"] == "completed"
        assert debug_snapshot["debug"]["ui"]["runtime_status"]["code"] == "watch"
        assert debug_snapshot["debug"]["ui"]["banner"]["code"] == "watch"
        assert debug_snapshot["debug"]["people"][0]["status_info"]["code"] == "watch"
        assert debug_snapshot["debug"]["people"][0]["runtime"]["execution_trace"] == ["supervisor", "search_agent"]
        assert debug_snapshot["debug"]["people"][0]["runtime_snapshot"]["state"]["execution_trace"] == ["supervisor", "search_agent"]
        assert debug_snapshot["debug"]["people"][0]["runtime_snapshot"]["state"]["revision_count"] == 1
        assert debug_snapshot["debug"]["people"][0]["runtime_snapshot"]["state"]["max_revisions"] == 2
        assert debug_snapshot["debug"]["people"][0]["runtime_reflection"]["tool_summary"]["total_calls"] == 1
        assert debug_snapshot["debug"]["people"][0]["runtime_pdca"]["status"] == "watch"
        assert debug_snapshot["debug"]["people"][0]["runtime_pdca"]["do"]["items"] == [
            "search_agent 调用 search_person_info，成功，0ms"
        ]
        assert debug_snapshot["debug"]["people"][0]["runtime_quality"]["status"] == "watch"
        assert debug_snapshot["debug"]["people"][0]["runtime_quality"]["measurement"]["label"] == "测"
        assert "tool_traces 记录 1 次调用。" in debug_snapshot["debug"]["people"][0]["runtime_quality"]["measurement"]["findings"]
        assert debug_snapshot["debug"]["people"][0]["runtime"]["status"] == "ok"
        assert debug_snapshot["debug"]["people"][0]["runtime"]["tool_traces"][0]["agent_step"] == "search_agent"
        assert debug_snapshot["debug"]["people"][0]["runtime"]["tool_traces"][0]["input_summary"] == "'霍去病'"
        assert debug_snapshot["debug"]["people"][0]["runtime"]["tool_traces"][0]["output_summary"] == "{'person': '霍去病'}"
        assert query_payload["ok"] is True
        assert query_payload["total"] >= 1
        list_item = next(item for item in query_payload["tasks"] if item["id"] == submit["task_id"])
        assert list_item["status"] == "completed"
        assert list_item["status_info"]["code"] == "watch"
        assert stats["task_count"] >= 1
        assert stats["db_path"].endswith("task_state.sqlite3")
        assert stats["db_size_bytes"] >= stats["db_main_size_bytes"]
        assert maintain["ok"] is True
        assert "stats" in maintain
    finally:
        service.shutdown()


def test_task_debug_ui_banner_prefers_runtime_degraded_signal(tmp_path):
    service = _build_service(
        tmp_path,
        generate_for_person=lambda _client, person, **_kwargs: {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_agent_runtime": {
                "person": person,
                "state": {
                    "llm_calls_used": 1,
                    "llm_calls_limit": 4,
                    "degraded_reasons": ["map_agent:timeout"],
                    "execution_trace": ["supervisor", "map_agent"],
                    "tool_traces": [],
                    "memory_hits": {},
                    "memory_misses": {},
                },
            },
            "_profile": {
                "person": {"name": person},
                "locations": [],
                "mapStyle": {},
            },
        },
    )
    try:
        submit = service.submit_task("霍去病")
        snapshot = _wait_for_task(service, submit["task_id"])
        debug_snapshot = service.task_debug_snapshot(submit["task_id"])

        assert snapshot["status"] == "completed"
        assert debug_snapshot["debug"]["result"]["status"] == "completed"
        assert debug_snapshot["debug"]["meta"]["status"] == "degraded"
        assert debug_snapshot["debug"]["ui"]["runtime_status"]["code"] == "degraded"
        assert debug_snapshot["debug"]["ui"]["banner"]["code"] == "degraded"
    finally:
        service.shutdown()


def test_task_debug_ui_banner_keeps_partial_failed_over_runtime_watch(tmp_path):
    def _generate(_client, person, **_kwargs):
        if person == "杜甫":
            return {"ok": False, "person": person, "error": "杜甫 no data"}
        return {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_agent_runtime": {
                "person": person,
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
            "_profile": {
                "person": {"name": person},
                "locations": [],
                "mapStyle": {},
            },
        }

    service = _build_service(tmp_path, generate_for_person=_generate)
    try:
        submit = service.submit_task("李白 杜甫")
        debug_snapshot = service.task_debug_snapshot(submit["task_id"])
        end = time.time() + 2.0
        while time.time() < end and debug_snapshot.get("status") != "partial_failed":
            time.sleep(0.02)
            debug_snapshot = service.task_debug_snapshot(submit["task_id"])

        assert debug_snapshot["status"] == "partial_failed"
        assert debug_snapshot["debug"]["meta"]["status"] == "watch"
        assert debug_snapshot["debug"]["result"]["status"] == "partial_failed"
        assert debug_snapshot["debug"]["ui"]["runtime_status"]["code"] == "watch"
        assert debug_snapshot["debug"]["ui"]["banner"]["code"] == "partial_failed"
    finally:
        service.shutdown()


def test_task_service_counts_partial_failed_in_storage_stats(tmp_path):
    def _generate(_client, person, **_kwargs):
        if person == "杜甫":
            return {"ok": False, "person": person, "error": "杜甫 no data"}
        return {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    service = _build_service(tmp_path, generate_for_person=_generate)
    try:
        submit = service.submit_task("李白 杜甫")
        snapshot = _wait_for_task(service, submit["task_id"])
        stats = service.storage_stats()

        assert snapshot["status"] == "partial_failed"
        assert stats["task_count"] >= 1
        assert stats["partial_failed_count"] == 1
    finally:
        service.shutdown()


def test_task_service_refreshes_waiting_queue_positions(tmp_path):
    release_first = threading.Event()
    first_started = threading.Event()

    def _generate(_client, person, **_kwargs):
        if person == "霍去病":
            first_started.set()
            release_first.wait(timeout=1.0)
        return {
            "ok": True,
            "person": person,
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {
                "person": {"name": person},
                "locations": [{"name": "长安", "modernName": "西安", "lat": 34.26, "lng": 108.95}],
                "mapStyle": {},
            },
        }

    service = _build_service(tmp_path, max_concurrency=1, generate_for_person=_generate)
    try:
        service.submit_task("霍去病")
        second = service.submit_task("李白")
        assert first_started.wait(timeout=1.0) is True

        end = time.time() + 1.0
        queued_snapshot = {}
        while time.time() < end:
            queued_snapshot = service.snapshot_task(second["task_id"])
            if queued_snapshot.get("status") == "queued" and queued_snapshot.get("queue", {}).get("position") == 1:
                break
            time.sleep(0.02)

        assert queued_snapshot["status"] == "queued"
        assert queued_snapshot["queue"]["position"] == 1
        assert queued_snapshot["queue"]["active"] == 1
    finally:
        release_first.set()
        service.shutdown()
