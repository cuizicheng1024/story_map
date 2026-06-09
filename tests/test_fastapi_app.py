import logging
import sys
import time
from pathlib import Path

import anyio
import httpx
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_map
from story_map import APP
from proxy import ProxyService


pytestmark = pytest.mark.anyio


def _make_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=APP)


async def test_health_endpoint_returns_ok():
    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "story_map"


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


async def test_existing_person_story_map_page_loads_normally(monkeypatch, tmp_path):
    source_html = REPO_ROOT / "artifacts" / "story_map" / "王昭君.html"
    target_html = tmp_path / "王昭君.html"
    target_html.write_text(source_html.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_active_story_map_dir", lambda: str(tmp_path))
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_public_story_map_dirs", lambda: [str(tmp_path)])

    async with httpx.AsyncClient(transport=_make_transport(), base_url="http://testserver") as client:
        response = await client.get("/%E7%8E%8B%E6%98%AD%E5%90%9B.html")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "王昭君" in response.text
    assert "window.__EXPORT_DATA__" in response.text


async def test_generate_then_poll_task_flow(monkeypatch):
    def _fake_generate(_client, person, **_kwargs):
        assert person == "霍去病"
        return {
            "ok": True,
            "person": person,
            "markdown_path": "/tmp/霍去病.md",
            "html_path": "/tmp/霍去病.html",
            "_profile": {
                "person": {"name": person},
                "locations": [],
                "mapStyle": {},
            },
        }

    monkeypatch.setattr(story_map._TASK_SERVICE, "_generate_for_person", _fake_generate)
    monkeypatch.setattr(story_map._TASK_SERVICE, "_ensure_profile_exports", lambda *args, **kwargs: {})

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
    assert snapshot["result"]["ok"] is True
    assert snapshot["result"]["people"] == ["霍去病"]
    assert snapshot["result"]["results"][0]["person"] == "霍去病"


async def test_ai_proxy_prefers_local_agent(monkeypatch):
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
    assert payload["meta"]["used_fallback"] is False


async def test_ai_proxy_uses_llm_when_local_agent_not_handled(monkeypatch):
    class _FakeClient:
        def think(self, messages, temperature=0.1):
            assert messages[0]["content"] == "介绍一下他"
            assert temperature == 0.2
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
                "temperature": 0.2,
                "context": {"personName": "苏轼"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "这是模型回答。"
    assert payload["meta"]["source"] == "llm"
    assert payload["meta"]["used_fallback"] is False


def test_proxy_service_resets_executor_after_timeout(monkeypatch):
    class _SlowClient:
        def think(self, _messages, temperature=0.1):
            assert temperature == 0.1
            time.sleep(0.05)
            return "slow"

    service = ProxyService(
        get_llm_client=lambda: _SlowClient(),
        local_agent_reply=lambda _data: {"handled": False, "content": "", "person_name": ""},
        local_history_reply=lambda _messages: "fallback",
        logger=logging.getLogger("proxy-test"),
        max_workers=1,
        timeout_env_name="TEST_PROXY_TIMEOUT",
    )
    monkeypatch.setenv("TEST_PROXY_TIMEOUT", "0")
    original_executor = service._executor
    try:
        status, payload = service.proxy_llm({"messages": [{"role": "user", "content": "介绍一下他"}]})

        assert status == 200
        assert payload["choices"][0]["message"]["content"] == "fallback"
        assert payload["meta"]["used_fallback"] is True
        assert payload["meta"]["source"] == "fallback"
        assert service._executor is not original_executor
    finally:
        service.shutdown()
