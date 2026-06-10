import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_agents


def _build_client():
    return story_agents.StoryAgentLLM(
        model="MiniMax-M3",
        apiKey="test-key",
        baseUrl="https://api.minimaxi.com/anthropic",
        timeout=1,
    )


def test_story_agent_llm_records_success_trace(monkeypatch):
    client = _build_client()

    def _fake_think_minimax(messages, temperature=0, request_id=""):
        assert messages[0]["content"] == "ping"
        assert temperature == 0
        assert request_id
        return "OK", {"endpoint": "https://api.minimaxi.com/anthropic/v1/messages", "status_code": 200, "duration_ms": 12}

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0)
    trace = client.latest_trace()

    assert content == "OK"
    assert trace["success"] is True
    assert trace["classification"] == "ok"
    assert trace["status_code"] == 200
    assert trace["request_id"]
    assert trace["message_stats"]["message_count"] == 1


def test_story_agent_llm_stops_retry_on_non_retryable_error(monkeypatch):
    client = _build_client()
    calls = {"count": 0}

    def _fake_think_minimax(_messages, temperature=0, request_id=""):
        _ = temperature
        calls["count"] += 1
        raise story_agents.LLMRequestError(
            "HTTP 401: unauthorized",
            classification="auth",
            request_id=request_id or "req",
            provider="minimax",
            endpoint="https://api.minimaxi.com/anthropic/v1/messages",
            status_code=401,
            retryable=False,
        )

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0)
    trace = client.latest_trace()

    assert content is None
    assert calls["count"] == 1
    assert trace["success"] is False
    assert trace["classification"] == "auth"
    assert trace["status_code"] == 401
    assert trace["retryable"] is False


def test_story_agent_health_check_collects_results(monkeypatch):
    client = _build_client()

    def _fake_think_minimax(_messages, temperature=0, request_id=""):
        _ = (temperature, request_id)
        return "OK", {"endpoint": "https://api.minimaxi.com/anthropic/v1/messages", "status_code": 200, "duration_ms": 8}

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    report = client.check_health(attempts=2)

    assert report["ok"] is True
    assert report["attempts"] == 2
    assert report["success_count"] == 2
    assert len(report["results"]) == 2
    assert report["results"][0]["trace"]["classification"] == "ok"
