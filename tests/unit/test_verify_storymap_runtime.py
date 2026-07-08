from __future__ import annotations

from tools.reports.verify_storymap_runtime import verify_runtime

def test_verify_runtime_reports_success_for_healthy_service():
    responses = {
        "http://story.test/health": {"ok": True, "service": "story_map"},
        "http://story.test/health/ready": {"ok": True, "alerts": []},
        "http://story.test/generate": {"ok": True, "task_id": "task-1"},
        "http://story.test/task?id=task-1": {"status": "completed", "ok": True},
    }
    texts = {
        "http://story.test/metrics": "storymap_readiness 1\nstorymap_generate_readiness 1\n",
        "http://story.test/": "<html>人类群星闪耀时<div id='pixelGenCompactText'></div></html>",
        "http://story.test/%E6%9D%8E%E7%99%BD.html": "<html>李白<script>window.__BUILD_META__={};</script></html>",
    }

    def _fake_json(url: str, *, method: str = "GET", body=None, timeout: float = 20.0):
        assert timeout == 5.0
        if method == "POST":
            assert body == {"person": "李白"}
            return responses["http://story.test/generate"]
        return responses[url]

    def _fake_text(url: str, *, timeout: float = 20.0):
        assert timeout == 5.0
        return texts[url]

    report = verify_runtime(
        base_url="http://story.test",
        timeout=5.0,
        poll_timeout=1.0,
        person="李白",
        request_json=_fake_json,
        request_text=_fake_text,
        sleep=lambda _seconds: None,
        now=lambda: 0.0,
    )

    assert report["ok"] is True
    assert [item["name"] for item in report["checks"]] == [
        "health",
        "readiness",
        "metrics",
        "homepage",
        "profile_page",
        "generate_submit",
        "generate_task_terminal",
    ]

def test_verify_runtime_reports_failed_generation_task():
    responses = {
        "http://story.test/health": {"ok": True},
        "http://story.test/health/ready": {"ok": True},
        "http://story.test/generate": {"ok": True, "task_id": "task-1"},
        "http://story.test/task?id=task-1": {"status": "timed_out", "ok": False},
    }
    texts = {
        "http://story.test/metrics": "storymap_readiness 1\nstorymap_generate_readiness 1\n",
        "http://story.test/": "<html>人类群星闪耀时<div id='pixelGenCompactText'></div></html>",
        "http://story.test/%E6%9D%8E%E7%99%BD.html": "<html>李白<script>window.__BUILD_META__={};</script></html>",
    }

    report = verify_runtime(
        base_url="http://story.test",
        poll_timeout=0.1,
        request_json=lambda url, **kwargs: responses[url if kwargs.get("method") != "POST" else "http://story.test/generate"],
        request_text=lambda url, **kwargs: texts[url],
        sleep=lambda _seconds: None,
        now=lambda: 0.0,
    )

    assert report["ok"] is False
    terminal = next(item for item in report["checks"] if item["name"] == "generate_task_terminal")
    assert terminal["status"] == "timed_out"
