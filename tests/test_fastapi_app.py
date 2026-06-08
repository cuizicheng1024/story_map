import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_map
from story_map import APP


client = TestClient(APP)


def test_health_endpoint_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "story_map"


def test_root_serves_homepage_html(monkeypatch, tmp_path):
    homepage = tmp_path / "index.html"
    homepage.write_text("<html><body>StoryMap Home</body></html>", encoding="utf-8")
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_active_story_map_dir", lambda: str(tmp_path))
    monkeypatch.setattr(story_map._STATIC_SERVICE, "_public_story_map_dirs", lambda: [str(tmp_path)])

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<html" in response.text.lower()


def test_generate_then_poll_task_flow(monkeypatch):
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

    submit = client.post("/generate", json={"person": "霍去病"})

    assert submit.status_code == 200
    payload = submit.json()
    assert payload["ok"] is True
    task_id = payload["task_id"]

    snapshot = None
    for _ in range(40):
        response = client.get("/task", params={"id": task_id})
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot.get("status") == "completed":
            break
        time.sleep(0.05)

    assert snapshot is not None
    assert snapshot["status"] == "completed"
    assert snapshot["result"]["ok"] is True
    assert snapshot["result"]["people"] == ["霍去病"]
    assert snapshot["result"]["results"][0]["person"] == "霍去病"
