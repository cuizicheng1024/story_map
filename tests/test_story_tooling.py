import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from story_tooling import invoke_tool, tool


def test_invoke_tool_retries_and_records_trace():
    calls = {"count": 0}

    @tool(
        name="flaky_tool",
        description="test",
        input_schema={"type": "string"},
        output_schema={"type": "string"},
        retry_count=1,
        timeout_seconds=0.5,
        permission="network_read",
        cost_tier="medium",
    )
    def flaky_tool(value: str) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")
        return value.upper()

    traces = []
    result = invoke_tool(flaky_tool, "li bai", trace_collector=traces, agent_step="search_agent")

    assert result == "LI BAI"
    assert calls["count"] == 2
    assert len(traces) == 2
    assert traces[0]["success"] is False
    assert traces[1]["success"] is True
    assert traces[1]["agent_step"] == "search_agent"
    assert traces[1]["permission"] == "network_read"
    assert traces[1]["cost_tier"] == "medium"
    assert traces[1]["input_summary"] == "'li bai'"
    assert traces[1]["output_summary"] == "'LI BAI'"


def test_invoke_tool_rejects_input_schema_mismatch():
    @tool(
        name="strict_tool",
        description="test",
        input_schema={"type": "string"},
        output_schema={"type": "string"},
    )
    def strict_tool(value: str) -> str:
        return value

    try:
        invoke_tool(strict_tool, {"bad": "payload"})
    except ValueError as exc:
        assert "输入不符合 schema" in str(exc)
    else:
        raise AssertionError("expected schema validation failure")


def test_invoke_tool_marks_timeout_in_trace():
    @tool(
        name="slow_tool",
        description="test",
        input_schema={"type": "string"},
        output_schema={"type": "string"},
        timeout_seconds=0.01,
    )
    def slow_tool(value: str) -> str:
        time.sleep(0.03)
        return value

    traces = []
    try:
        invoke_tool(slow_tool, "x", trace_collector=traces)
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected timeout")

    assert len(traces) == 1
    assert traces[0]["timed_out"] is True
    assert traces[0]["success"] is False


def test_invoke_tool_timeout_does_not_wait_for_worker_completion():
    @tool(
        name="slow_tool",
        description="test",
        input_schema={"type": "string"},
        output_schema={"type": "string"},
        timeout_seconds=0.01,
    )
    def slow_tool(value: str) -> str:
        time.sleep(0.2)
        return value

    started = time.perf_counter()
    try:
        invoke_tool(slow_tool, "x")
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected timeout")

    elapsed = time.perf_counter() - started
    assert elapsed < 0.12
