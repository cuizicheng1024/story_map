import sys

from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.agent import registry as story_agents


def _build_client():
    return story_agents.StoryAgentLLM(
        model="MiniMax-M3",
        apiKey="test-key",
        baseUrl="https://api.minimaxi.com/v1",
        timeout=1,
    )


def test_story_agent_llm_verifies_ssl_by_default():
    client = _build_client()

    assert client.verify_ssl is True
    assert client.health_snapshot()["verify_ssl"] is True


def test_story_agent_llm_allows_explicit_insecure_ssl(monkeypatch):
    monkeypatch.setenv("STORY_AGENT_ALLOW_INSECURE_SSL", "1")

    client = _build_client()

    assert client.verify_ssl is False
    assert client.health_snapshot()["verify_ssl"] is False


def test_story_agent_llm_defaults_to_minimax_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client = _build_client()

    assert client.provider == "minimax"
    assert client.health_snapshot()["provider"] == "minimax"
    assert client.health_snapshot()["uses_anthropic_api"] is False


def test_story_agent_llm_ignores_removed_qveris_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qveris")

    client = _build_client()

    assert client.provider == "minimax"
    assert client.health_snapshot()["provider"] == "minimax"


def test_story_agent_llm_uses_anthropic_when_base_url_explicit(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client = story_agents.StoryAgentLLM(
        model="MiniMax-M3",
        apiKey="test-key",
        baseUrl="https://api.minimaxi.com/anthropic",
        timeout=1,
    )

    assert client.health_snapshot()["uses_anthropic_api"] is True


def test_story_agent_llm_records_success_trace(monkeypatch):
    client = _build_client()

    def _fake_think_minimax(messages, temperature=0, request_id="", timeout_seconds=None):
        assert messages[0]["content"] == "ping"
        assert temperature == 0
        assert request_id
        assert timeout_seconds == 1
        return "OK", {"endpoint": "https://api.minimaxi.com/v1/chat/completions", "status_code": 200, "duration_ms": 12}

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

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = temperature
        assert timeout_seconds == 1
        calls["count"] += 1
        raise story_agents.LLMRequestError(
            "HTTP 401: unauthorized",
            classification="auth",
            request_id=request_id or "req",
            provider="minimax",
            endpoint="https://api.minimaxi.com/v1/chat/completions",
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


def test_classify_request_exception_marks_ssl_errors():
    exc = story_agents.requests.exceptions.SSLError("certificate verify failed")

    assert story_agents._classify_request_exception(exc) == "ssl"


def test_story_agent_health_check_collects_results(monkeypatch):
    client = _build_client()

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = (temperature, request_id)
        assert timeout_seconds == 1
        return "OK", {"endpoint": "https://api.minimaxi.com/v1/chat/completions", "status_code": 200, "duration_ms": 8}

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    report = client.check_health(attempts=2)

    assert report["ok"] is True
    assert report["attempts"] == 2
    assert report["success_count"] == 2
    assert len(report["results"]) == 2
    assert report["results"][0]["trace"]["classification"] == "ok"


def test_story_agent_llm_supports_per_call_timeout_override(monkeypatch):
    client = _build_client()
    observed = []

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = (temperature, request_id)
        observed.append(timeout_seconds)
        return "OK", {"endpoint": "https://api.minimaxi.com/v1/chat/completions", "status_code": 200, "duration_ms": 6}

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0, timeout=7, max_retries=1)

    assert content == "OK"
    assert observed == [7]
    assert client.timeout == 1
    assert client.latest_trace()["timeout"] == 7
    assert client.latest_trace()["max_retries"] == 1


def test_story_agent_llm_clamps_timeout_with_runtime_budget(monkeypatch):
    observed = []
    client = story_agents.StoryAgentLLM(
        model="MiniMax-M3",
        apiKey="test-key",
        baseUrl="https://api.minimaxi.com/v1",
        timeout=300,
        timeout_resolver=lambda: 45,
    )

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = (temperature, request_id)
        observed.append(timeout_seconds)
        return "OK", {"endpoint": "https://api.minimaxi.com/v1/chat/completions", "status_code": 200, "duration_ms": 6}

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0, timeout=120, max_retries=1)

    assert content == "OK"
    assert observed == [45]
    assert client.timeout == 300
    assert client.latest_trace()["timeout"] == 45


def test_story_agent_llm_post_json_uses_explicit_timeout_override(monkeypatch):
    client = story_agents.StoryAgentLLM(
        model="MiniMax-M3",
        apiKey="test-key",
        baseUrl="https://api.minimaxi.com/v1",
        timeout=300,
    )
    observed = {}

    class _FakeResponse:
        status_code = 200
        ok = True
        headers = {}
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    def _fake_post(*_args, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        return _FakeResponse()

    monkeypatch.setattr(story_agents.requests, "post", _fake_post)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0, timeout=7, max_retries=1)

    assert content == "OK"
    assert observed["timeout"] == (7, 7)


def test_story_agent_llm_supports_per_call_retry_override(monkeypatch):
    client = _build_client()
    calls = {"count": 0}

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = temperature
        assert timeout_seconds == 1
        calls["count"] += 1
        raise story_agents.LLMRequestError(
            "timeout",
            classification="timeout",
            request_id=request_id or "req",
            provider="minimax",
            endpoint="https://api.minimaxi.com/v1/chat/completions",
            retryable=True,
        )

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    content = client.think([{"role": "user", "content": "ping"}], temperature=0, max_retries=1)

    assert content is None
    assert calls["count"] == 1
    assert client.latest_trace()["max_retries"] == 1


def test_story_agent_llm_health_snapshot_exposes_timeout_config_and_metrics():
    client = _build_client()
    snapshot = client.health_snapshot()

    assert snapshot["timeout_config"]["total"] == 1
    assert snapshot["timeout_config"]["connect"] == 1
    assert snapshot["timeout_config"]["read"] == 1
    assert "metrics" in snapshot
    assert snapshot["metrics"]["requests"] == 0


def test_story_agent_llm_uses_negative_cache_after_retryable_failure(monkeypatch):
    client = _build_client()
    calls = {"count": 0}

    def _fake_think_minimax(_messages, temperature=0, request_id="", timeout_seconds=None):
        _ = temperature
        assert timeout_seconds == 1
        calls["count"] += 1
        raise story_agents.LLMRequestError(
            "timeout",
            classification="timeout",
            request_id=request_id or "req",
            provider="minimax",
            endpoint="https://api.minimaxi.com/v1/chat/completions",
            retryable=False,
        )

    monkeypatch.setattr(client, "_think_minimax", _fake_think_minimax)

    assert client.think([{"role": "user", "content": "ping"}], temperature=0, max_retries=1) is None
    assert client.think([{"role": "user", "content": "ping"}], temperature=0, max_retries=1) is None
    trace = client.latest_trace()
    metrics = client.metrics_snapshot()

    assert calls["count"] == 1
    assert trace["classification"] == "timeout"
    assert trace["negative_cache_key"]
    assert metrics["negative_cache_hits"] == 1
    assert metrics["timeouts"] == 1
    assert metrics["failures"] == 1


def test_story_agent_llm_stream_uses_small_iter_lines_chunk_for_visible_streaming(monkeypatch):
    client = _build_client()
    observed = {}

    class _FakeResponse:
        ok = True
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_lines(self, chunk_size=512, decode_unicode=False):
            observed["chunk_size"] = chunk_size
            observed["decode_unicode"] = decode_unicode
            yield 'data: {"choices":[{"delta":{"content":"这"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"是"}}]}'
            yield 'data: [DONE]'

    def _fake_post(*_args, **kwargs):
        observed["stream"] = kwargs.get("stream")
        return _FakeResponse()

    monkeypatch.setattr(story_agents.requests, "post", _fake_post)

    chunks = list(
        client._stream_minimax_openai(
            [{"role": "user", "content": "ping"}],
            temperature=0,
            request_id="req-1",
            request_signature="sig-1",
            base_trace={},
        )
    )

    assert chunks == ["这", "是"]
    assert observed["stream"] is True
    assert observed["chunk_size"] == 1
    assert observed["decode_unicode"] is True
