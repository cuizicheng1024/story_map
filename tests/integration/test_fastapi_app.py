import logging
import sys
import time

import anyio
import httpx
import pytest


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_map
import map_client
from story_map import APP
from proxy import ProxyService


pytestmark = pytest.mark.anyio


def _make_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=APP)


@pytest.fixture(autouse=True)
def _reset_task_service_state():
    service = story_map._TASK_SERVICE
    with service._task_lock:
        removed_ids = list(service._tasks.keys())
        service._tasks.clear()
        service._delete_tasks_locked(removed_ids)
    with service._queue_lock:
        service._pending = 0
        service._active = 0
    yield
    with service._task_lock:
        removed_ids = list(service._tasks.keys())
        service._tasks.clear()
        service._delete_tasks_locked(removed_ids)
    with service._queue_lock:
        service._pending = 0
        service._active = 0


async def test_health_endpoint_returns_ok():
    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "story_map"


async def test_runtime_health_endpoint_returns_llm_and_geocode_snapshots(monkeypatch):
    class _FakeClient:
        def health_snapshot(self):
            return {
                "provider": "minimax",
                "metrics": {"requests": 3, "timeouts": 1},
                "timeout_config": {"total": 5, "connect": 2, "read": 5, "stream_read": 8},
            }

    monkeypatch.setattr(story_map._PROXY_SERVICE, "_get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(
        map_client,
        "geocode_metrics_snapshot",
        lambda: {"lookups": 10, "cache_hits": 4, "timeouts": 2, "timeout_rate": 0.2},
    )

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/health/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "story_map"
    assert payload["llm"]["ok"] is True
    assert payload["llm"]["health"]["provider"] == "minimax"
    assert payload["llm"]["health"]["metrics"]["requests"] == 3
    assert payload["geocode"]["ok"] is True
    assert payload["geocode"]["metrics"]["lookups"] == 10


async def test_runtime_debug_endpoints_reject_remote_requests_without_debug_token():
    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        runtime_response = await client.get("/health/runtime", headers={"x-forwarded-for": "8.8.8.8"})
        static_response = await client.get("/debug_static", headers={"x-forwarded-for": "8.8.8.8"})

    assert runtime_response.status_code == 403
    assert runtime_response.json()["detail"] == "runtime debug access denied"
    assert static_response.status_code == 403
    assert static_response.json()["detail"] == "runtime debug access denied"


async def test_runtime_health_endpoint_allows_remote_requests_with_debug_token(monkeypatch):
    monkeypatch.setenv("STORYMAP_RUNTIME_DEBUG_TOKEN", "secret-token")

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get(
            "/health/runtime",
            headers={
                "x-forwarded-for": "8.8.8.8",
                "x-storymap-debug-token": "secret-token",
            },
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True


async def test_root_serves_homepage_html(monkeypatch, tmp_path):
    homepage = tmp_path / "index.html"
    homepage.write_text("<html><body>StoryMap Home</body></html>", encoding="utf-8")
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_active_story_map_dir", lambda: str(tmp_path))
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_public_story_map_dirs", lambda: [str(tmp_path)])

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<html" in response.text.lower()


async def test_geovis_config_endpoint_serves_runtime_script(monkeypatch):
    monkeypatch.setenv("GEOVIS_TOKEN", "test-geovis-token")

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/geovis-config.js")

    assert response.status_code == 200
    assert "application/javascript" in response.headers.get("content-type", "")
    assert 'window.GEOVIS_TOKEN="test-geovis-token";' == response.text


async def test_existing_person_story_map_page_loads_normally(monkeypatch, tmp_path):
    target_html = tmp_path / "王昭君.html"
    target_html.write_text(
        "<html><body><h1>王昭君</h1><script>window.__EXPORT_DATA__ = {\"person\":{\"name\":\"王昭君\"}};</script></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_active_story_map_dir", lambda: str(tmp_path))
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_public_story_map_dirs", lambda: [str(tmp_path)])

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/%E7%8E%8B%E6%98%AD%E5%90%9B.html")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "王昭君" in response.text
    assert "window.__EXPORT_DATA__" in response.text


async def test_generate_get_is_rejected_and_does_not_submit_task(monkeypatch):
    monkeypatch.setattr(
        story_map._TASK_SERVICE,
        "submit_task",
        lambda _value: (_ for _ in ()).throw(AssertionError("GET /generate should not submit tasks")),
    )

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/generate", params={"person": "霍去病"})

    assert response.status_code == 405
    assert response.json() == {"ok": False, "error": "use POST /generate"}


async def test_generate_then_poll_task_flow(monkeypatch):
    def _fake_generate(_client, person, **_kwargs):
        assert person == "霍去病"
        return {
            "ok": True,
            "person": person,
            "markdown_path": "/tmp/霍去病.md",
            "html_path": "/tmp/霍去病.html",
            "_agent_runtime": {
                "person": person,
                "used_legacy_fallback": False,
                "state": {
                    "llm_calls_used": 2,
                    "llm_calls_limit": 4,
                    "degraded_reasons": ["editor_fallback"],
                    "execution_trace": ["supervisor", "search_agent", "editor_agent"],
                    "tool_traces": [{"tool_name": "search_person_info"}],
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

    monkeypatch.setattr(story_map._TASK_SERVICE, "_generate_for_person", _fake_generate)
    monkeypatch.setattr(story_map._TASK_SERVICE, "_ensure_profile_exports", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        story_map._TASK_SERVICE,
        "_refresh_stellar_homepage",
        lambda _person: {"ok": True, "index_path": "/tmp/index.html", "data_path": "/tmp/stellar_home_data.json"},
    )

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        submit = await client.post("/generate", json={"person": "霍去病"})

        assert submit.status_code == 200
        payload = submit.json()
        assert payload["ok"] is True
        task_id = payload["task_id"]

        snapshot = None
        for _ in range(40):
            response = await client.get("/task", params={"id": task_id})
            assert response.status_code == 200
            snapshot = response.json()
            if snapshot.get("status") == "completed":
                break
            await anyio.sleep(0.05)

    assert snapshot is not None
    assert snapshot["status"] == "completed"
    assert snapshot["status_info"]["code"] == "completed"
    assert snapshot["result"]["ok"] is True
    assert snapshot["result"]["status_info"]["code"] == "completed"
    assert snapshot["result"]["people"] == ["霍去病"]
    assert snapshot["result"]["results"][0]["person"] == "霍去病"
    assert snapshot["result"]["meta"]["llm_calls_used"] == 2
    assert snapshot["result"]["meta"]["llm_calls_limit"] == 4
    assert snapshot["result"]["meta"]["status"] == "degraded"
    assert snapshot["result"]["meta"]["status_info"]["code"] == "degraded"
    assert snapshot["result"]["meta"]["degraded"] is True
    assert snapshot["result"]["meta"]["degraded_reasons"] == ["editor_fallback"]
    assert snapshot["result"]["meta"]["execution_traces"]["霍去病"] == ["supervisor", "search_agent", "editor_agent"]
    assert snapshot["result"]["meta"]["tool_trace_count"] == 1
    assert snapshot["result"]["meta"]["used_legacy_fallback"] is False
    assert snapshot["result"]["meta"]["memory_hits"] == {"search": 1}
    assert snapshot["result"]["meta"]["memory_misses"] == {"place_map": 1}
    assert snapshot["result"]["archive"]["state"] in {"queued", "running", "completed"}


async def test_generate_daily_limit_rejects_second_request_from_same_ip(monkeypatch, tmp_path):
    calls = []

    def _fake_submit(value):
        calls.append(value)
        return {"ok": True, "task_id": f"task-{len(calls)}"}

    monkeypatch.setenv("MAP_STORY_GENERATE_DAILY_LIMIT", "1")
    monkeypatch.setenv("MAP_STORY_GENERATE_DAILY_LIMIT_PATH", str(tmp_path / "quota.json"))
    monkeypatch.setattr(story_map._TASK_SERVICE, "submit_task", _fake_submit)

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        first = await client.post("/generate", json={"person": "霍去病"}, headers={"x-forwarded-for": "1.2.3.4"})
        second = await client.post("/generate", json={"person": "李白"}, headers={"x-forwarded-for": "1.2.3.4"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"] == "daily generate limit exceeded (1/day)"
    assert second.json()["used"] == 1
    assert calls == ["霍去病"]


async def test_generate_daily_limit_is_scoped_per_ip(monkeypatch, tmp_path):
    calls = []

    def _fake_submit(value):
        calls.append(value)
        return {"ok": True, "task_id": f"task-{len(calls)}"}

    monkeypatch.setenv("MAP_STORY_GENERATE_DAILY_LIMIT", "1")
    monkeypatch.setenv("MAP_STORY_GENERATE_DAILY_LIMIT_PATH", str(tmp_path / "quota.json"))
    monkeypatch.setattr(story_map._TASK_SERVICE, "submit_task", _fake_submit)

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        first = await client.post("/generate", json={"person": "霍去病"}, headers={"x-forwarded-for": "1.2.3.4"})
        second = await client.post("/generate", json={"person": "李白"}, headers={"x-forwarded-for": "5.6.7.8"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["霍去病", "李白"]


async def test_task_endpoint_returns_200_for_failed_existing_task(monkeypatch):
    def _fake_generate(_client, person, **_kwargs):
        return {"ok": False, "person": person, "error": f"{person} failed"}

    monkeypatch.setattr(story_map._TASK_SERVICE, "_generate_for_person", _fake_generate)
    monkeypatch.setattr(story_map._TASK_SERVICE, "_ensure_profile_exports", lambda *args, **kwargs: {})

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        submit = await client.post("/generate", json={"person": "霍去病"})
        task_id = submit.json()["task_id"]
        snapshot = None
        for _ in range(40):
            response = await client.get("/task", params={"id": task_id})
            snapshot = response
            if response.json().get("status") == "failed":
                break
            await anyio.sleep(0.05)

    assert snapshot is not None
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["exists"] is True
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["status_info"]["code"] == "failed"

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        debug_response = await client.get("/task", params={"id": task_id, "debug": 1})
        debug_page = await client.get("/task/debug", params={"id": task_id})
        list_response = await client.get("/tasks", params={"limit": 10})
        storage_response = await client.get("/task/storage")
        maintain_response = await client.post("/task/storage/maintain", json={"prune_expired": True, "vacuum": False})

    assert debug_response.status_code == 200
    debug_payload = debug_response.json()
    assert debug_payload["exists"] is True
    assert debug_payload["ok"] is False
    assert debug_payload["debug"]["ui"]["banner"]["code"] == "failed"
    assert debug_payload["debug"]["meta"]["memory_hits"] == {}
    assert debug_payload["debug"]["meta"]["memory_misses"] == {}
    assert len(debug_payload["debug"]["people"]) == 1
    assert debug_payload["debug"]["people"][0]["person"] == "霍去病"
    assert debug_payload["debug"]["people"][0]["ok"] is False
    assert debug_payload["debug"]["people"][0]["status_info"]["code"] == "failed"
    assert debug_payload["debug"]["people"][0]["runtime"]["status"] == "empty"
    assert debug_payload["debug"]["people"][0]["runtime_reflection"]["status"] == "empty"

    assert debug_page.status_code == 200
    assert "Task Debug" in debug_page.text
    assert "霍去病" in debug_page.text
    assert "霍去病 failed" in debug_page.text
    assert list_response.status_code == 200
    assert storage_response.status_code == 200
    assert maintain_response.status_code == 200


async def test_task_is_marked_failed_when_homepage_refresh_failed(monkeypatch):
    def _fake_generate(_client, person, **_kwargs):
        return {
            "ok": False,
            "status": "degraded",
            "degraded": True,
            "person": person,
            "error": "首页刷新失败：timeout",
            "homepage_refresh_failed": True,
            "homepage_refresh_error": "timeout",
            "_homepage_refresh": {"ok": False, "returncode": 124, "output": "timeout"},
            "markdown_path": f"/tmp/{person}.md",
            "html_path": f"/tmp/{person}.html",
            "_profile": {"person": {"name": person}, "locations": [], "mapStyle": {}},
        }

    monkeypatch.setattr(story_map._TASK_SERVICE, "_generate_for_person", _fake_generate)
    monkeypatch.setattr(story_map._TASK_SERVICE, "_ensure_profile_exports", lambda *args, **kwargs: {})

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        submit = await client.post("/generate", json={"person": "霍去病"})
        task_id = submit.json()["task_id"]
        snapshot = None
        for _ in range(40):
            response = await client.get("/task", params={"id": task_id})
            snapshot = response.json()
            if snapshot.get("status") == "failed":
                break
            await anyio.sleep(0.05)

    assert snapshot is not None
    assert snapshot["status"] == "failed"
    assert snapshot["status_info"]["code"] == "failed"
    assert snapshot["result"]["failed_count"] == 1
    assert snapshot["result"]["results"][0]["homepage_refresh_failed"] is True
    assert snapshot["result"]["files"][0]["html"].endswith("/tmp/霍去病.html") or snapshot["result"]["files"][0]["html"] == "tmp/霍去病.html"

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        list_response = await client.get("/tasks", params={"limit": 10})

    assert list_response.status_code == 200
    items = list_response.json()["tasks"]
    target = next(item for item in items if item["id"] == task_id)
    assert target["status"] == "failed"
    assert target["result_ok"] is False


async def test_task_debug_surface_partial_failed_status(monkeypatch):
    def _fake_generate(_client, person, **_kwargs):
        if person == "杜甫":
            return {"ok": False, "person": person, "error": "杜甫 failed"}
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
                    "execution_trace": ["supervisor", "search_agent"],
                    "tool_traces": [{"tool_name": "search_person_info"}],
                    "memory_hits": {"search": 1},
                    "memory_misses": {},
                },
            },
            "_profile": {"person": {"name": person}, "locations": [], "mapStyle": {}},
        }

    monkeypatch.setattr(story_map._TASK_SERVICE, "_generate_for_person", _fake_generate)
    monkeypatch.setattr(story_map._TASK_SERVICE, "_ensure_profile_exports", lambda *args, **kwargs: {})

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        submit = await client.post("/generate", json={"person": "李白 杜甫"})
        task_id = submit.json()["task_id"]
        snapshot = None
        for _ in range(40):
            response = await client.get("/task", params={"id": task_id, "debug": 1})
            snapshot = response
            if response.json().get("status") == "partial_failed":
                break
            await anyio.sleep(0.05)
        debug_page = await client.get("/task/debug", params={"id": task_id})

    assert snapshot is not None
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["status"] == "partial_failed"
    assert payload["status_info"]["code"] == "partial_failed"
    assert payload["debug"]["result"]["status_info"]["code"] == "partial_failed"
    assert payload["debug"]["people"][0]["runtime_snapshot"]["state"]["llm_calls_used"] == 1
    assert payload["debug"]["people"][0]["runtime_reflection"]["status"] == "stable"
    assert "成功 1 人，失败 1 人" in payload["debug"]["ui"]["banner"]["hint"]
    assert debug_page.status_code == 200
    assert "部分失败" in debug_page.text
    assert "Runtime Reflection" in debug_page.text
    assert "Runtime Snapshot" in debug_page.text
    assert "杜甫" in debug_page.text


async def test_ai_proxy_falls_back_to_local_agent_when_llm_unavailable(monkeypatch):
    def _fake_local_agent(data):
        assert data["context"]["personName"] == "苏轼"
        return {
            "handled": True,
            "content": "这是本地人物档案给出的回答。",
            "person_name": "苏轼",
        }

    monkeypatch.setattr(story_map._PROXY_SERVICE, "_local_agent_reply", _fake_local_agent)
    monkeypatch.setattr(
        story_map._PROXY_SERVICE,
        "_get_llm_client",
        lambda: (_ for _ in ()).throw(AssertionError("local agent hit should skip llm")),
    )

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/proxy",
            json={
                "messages": [{"role": "user", "content": "他去过哪里？"}],
                "context": {"personName": "苏轼"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "这是本地人物档案给出的回答。"
    assert payload["meta"]["source"] == "local_agent"
    assert payload["meta"]["used_fallback"] is True


async def test_ai_proxy_uses_llm_when_local_agent_not_handled(monkeypatch):
    class _FakeClient:
        def think(self, messages, temperature=0.1):
            assert messages[0]["content"] == "介绍一下他"
            assert temperature == 0.5
            return "这是模型回答。"

    monkeypatch.setattr(
        story_map._PROXY_SERVICE,
        "_local_agent_reply",
        lambda _data: {"handled": False, "content": "", "person_name": ""},
    )
    monkeypatch.setattr(story_map._PROXY_SERVICE, "_get_llm_client", lambda: _FakeClient())

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/proxy",
            json={
                "messages": [{"role": "user", "content": "介绍一下他"}],
                "temperature": 0.5,
                "context": {"personName": "苏轼"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "这是模型回答。"
    assert payload["meta"]["source"] == "llm"
    assert payload["meta"]["used_fallback"] is False


async def test_ai_proxy_streams_llm_chunks_when_requested(monkeypatch):
    class _FakeClient:
        def latest_trace(self):
            return {"classification": "ok", "request_id": "trace-1"}

        def metrics_snapshot(self):
            return {"requests": 1, "successes": 1}

        def stream_think(self, messages, temperature=0.1):
            assert messages[0]["content"] == "介绍一下他"
            assert temperature == 0.5
            yield "这是"
            yield "流式回答。"

    monkeypatch.setattr(
        story_map._PROXY_SERVICE,
        "_local_agent_reply",
        lambda _data: {"handled": False, "content": "", "person_name": ""},
    )
    monkeypatch.setattr(story_map._PROXY_SERVICE, "_get_llm_client", lambda: _FakeClient())

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/proxy",
            json={
                "messages": [{"role": "user", "content": "介绍一下他"}],
                "temperature": 0.5,
                "stream": True,
                "context": {"personName": "苏轼"},
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert '"type": "delta", "delta": "这是"' in response.text
    assert '"type": "delta", "delta": "流式回答。"' in response.text
    assert '"type": "meta"' in response.text
    assert '"source": "llm"' in response.text
    assert '"llm_trace"' in response.text
    assert '"llm_metrics"' in response.text


async def test_ai_proxy_streams_local_fallback_when_llm_fails(monkeypatch):
    def _fake_local_agent(data):
        assert data["context"]["personName"] == "苏轼"
        return {
            "handled": True,
            "content": "这是本地人物档案给出的回答。",
            "person_name": "苏轼",
        }

    monkeypatch.setattr(story_map._PROXY_SERVICE, "_local_agent_reply", _fake_local_agent)
    monkeypatch.setattr(
        story_map._PROXY_SERVICE,
        "_get_llm_client",
        lambda: (_ for _ in ()).throw(RuntimeError("llm down")),
    )

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/proxy",
            json={
                "messages": [{"role": "user", "content": "他去过哪里？"}],
                "stream": True,
                "context": {"personName": "苏轼"},
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "这是本地人物档案给出的回答。" in response.text
    assert '"source": "local_agent"' in response.text
    assert '"used_fallback": true' in response.text


def test_proxy_service_resets_executor_after_timeout(monkeypatch):
    class _SlowClient:
        def latest_trace(self):
            return {"classification": "timeout", "request_id": "slow-trace"}

        def metrics_snapshot(self):
            return {"requests": 1, "timeouts": 1}

        def think(self, _messages, temperature=0.5):
            assert temperature == 0.5
            time.sleep(1.2)
            return "slow"

    service = ProxyService(
        get_llm_client=lambda: _SlowClient(),
        local_agent_reply=lambda _data: {"handled": False, "content": "", "person_name": ""},
        local_history_reply=lambda _messages: "fallback",
        logger=logging.getLogger("proxy-test"),
        max_workers=1,
        timeout_env_name="TEST_PROXY_TIMEOUT",
    )
    monkeypatch.setenv("TEST_PROXY_TIMEOUT", "1")
    original_executor = service._executor
    try:
        status, payload = service.proxy_llm({"messages": [{"role": "user", "content": "介绍一下他"}]})

        assert status == 200
        assert payload["choices"][0]["message"]["content"] == "fallback"
        assert payload["meta"]["used_fallback"] is True
        assert payload["meta"]["source"] == "fallback"
        assert payload["meta"]["fallback_reason"] == "timeout"
        assert payload["meta"]["llm_trace"]["classification"] == "timeout"
        assert payload["meta"]["llm_metrics"]["timeouts"] == 1
        assert service._executor is not original_executor
    finally:
        service.shutdown()


def test_proxy_service_uses_larger_default_stream_fallback_chunks():
    chunks = list(ProxyService._chunk_text("甲" * 160))

    assert len(chunks) == 3
    assert len(chunks[0]) == 72
    assert len(chunks[1]) == 72
    assert len(chunks[2]) == 16
