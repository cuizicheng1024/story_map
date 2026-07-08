import sys
import json
import time
import threading
from pathlib import Path

from storymap.script.core import artifacts

def test_active_story_map_dir_uses_artifact_directory(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    artifact_dir.mkdir(parents=True)

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))

    assert artifacts._active_story_map_dir() == str(artifact_dir)

def test_public_story_map_dirs_only_return_artifact_directory(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    artifact_dir.mkdir(parents=True)

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))

    assert artifacts._public_story_map_dirs() == [str(artifact_dir)]

def test_save_outputs_sanitize_unsafe_names(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    artifact_dir.mkdir(parents=True)

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))

    html_path = artifacts.save_html("苏轼/黄州", "<html></html>")
    geojson_path = artifacts.save_geojson("苏轼/黄州", {"type": "FeatureCollection", "features": []})
    csv_path = artifacts.save_csv("苏轼/黄州", "name\n苏轼\n")

    assert Path(html_path).name == "苏轼_黄州.html"
    assert Path(geojson_path).name == "苏轼_黄州.geojson"
    assert Path(csv_path).name == "苏轼_黄州.csv"

def test_update_home_coords_writes_wgs84_fields_and_coord_system(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    artifact_dir.mkdir(parents=True)
    home_path = artifact_dir / "stellar_home_data.json"
    home_path.write_text(json.dumps({"nodes": [{"person": "苏轼"}]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))

    status, payload = artifacts._update_home_coords({"items": {"苏轼": [30.25, 120.16]}}, threading.Lock())

    assert status == 200
    assert payload["ok"] is True
    saved = json.loads(home_path.read_text(encoding="utf-8"))
    node = saved["nodes"][0]
    assert node["birth_lat"] == 30.25
    assert node["birth_lng"] == 120.16
    assert node["birth_lat_wgs84"] == 30.25
    assert node["birth_lng_wgs84"] == 120.16
    assert node["birth_coord_system"] == "WGS84"

def test_update_home_coords_invalidates_renderer_cache(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    artifact_dir.mkdir(parents=True)
    home_path = artifact_dir / "stellar_home_data.json"
    home_path.write_text(json.dumps({"nodes": [{"person": "苏轼"}]}, ensure_ascii=False), encoding="utf-8")
    invalidated = []

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))
    monkeypatch.setattr(artifacts, "_invalidate_stellar_home_render_cache", lambda: invalidated.append(True))

    status, payload = artifacts._update_home_coords({"items": {"苏轼": [30.25, 120.16]}}, threading.Lock())

    assert status == 200
    assert payload["ok"] is True
    assert invalidated == [True]

def test_refresh_stellar_homepage_invalidates_renderer_cache_on_success(monkeypatch):
    invalidated = []
    commands = []

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: "/tmp/story_map")
    monkeypatch.setattr(artifacts, "_story_md_dir", lambda: "/tmp/story")
    monkeypatch.setattr(artifacts, "_project_root", lambda: "/tmp/project")
    monkeypatch.setattr(artifacts, "_invalidate_stellar_home_render_cache", lambda: invalidated.append(True))

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(command, **kwargs):
        _ = kwargs
        commands.append(command)
        return Completed()

    monkeypatch.setattr(artifacts.subprocess, "run", _fake_run)

    result = artifacts.refresh_stellar_homepage("苏轼")

    assert result["ok"] is True
    assert result["person"] == "苏轼"
    assert invalidated == [True]
    assert commands == [
        [sys.executable, "tools/build_people_summary_index.py"],
        [sys.executable, "tools/build_work_summary_index.py"],
        [
            sys.executable,
            "tools/build/homepage/main.py",
            "--story-map-dir",
            "/tmp/story_map",
            "--story-md-dir",
            "/tmp/story",
        ],
    ]

def test_refresh_stellar_homepage_passes_timeout_to_subprocess(monkeypatch):
    invalidated = []
    timeouts = []

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: "/tmp/story_map")
    monkeypatch.setattr(artifacts, "_story_md_dir", lambda: "/tmp/story")
    monkeypatch.setattr(artifacts, "_project_root", lambda: "/tmp/project")
    monkeypatch.setattr(artifacts, "_invalidate_stellar_home_render_cache", lambda: invalidated.append(True))
    monkeypatch.setattr(artifacts, "_homepage_refresh_timeout_seconds", lambda: 33)

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(command, **kwargs):
        _ = command
        timeouts.append(kwargs.get("timeout"))
        return Completed()

    monkeypatch.setattr(artifacts.subprocess, "run", _fake_run)

    result = artifacts.refresh_stellar_homepage("苏轼")

    assert result["ok"] is True
    assert timeouts == [33, 33, 33]
    assert invalidated == [True]

def test_refresh_stellar_homepage_returns_timeout_result_without_invalidating_cache(monkeypatch):
    invalidated = []
    commands = []

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: "/tmp/story_map")
    monkeypatch.setattr(artifacts, "_story_md_dir", lambda: "/tmp/story")
    monkeypatch.setattr(artifacts, "_project_root", lambda: "/tmp/project")
    monkeypatch.setattr(artifacts, "_invalidate_stellar_home_render_cache", lambda: invalidated.append(True))
    monkeypatch.setattr(artifacts, "_homepage_refresh_timeout_seconds", lambda: 7)

    def _fake_run(command, **kwargs):
        _ = kwargs
        commands.append(command)
        raise artifacts.subprocess.TimeoutExpired(cmd=command, timeout=7, output="slow stdout", stderr="slow stderr")

    monkeypatch.setattr(artifacts.subprocess, "run", _fake_run)

    result = artifacts.refresh_stellar_homepage("苏轼")

    assert result["ok"] is False
    assert result["returncode"] == 124
    assert "Command timed out after 7s" in result["output"]
    assert "slow stdout" in result["output"]
    assert invalidated == []
    assert commands == [[sys.executable, "tools/build_people_summary_index.py"]]

def test_refresh_stellar_homepage_serializes_concurrent_calls(monkeypatch):
    entered = []
    active = 0
    max_active = 0
    guard = threading.Lock()

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: "/tmp/story_map")
    monkeypatch.setattr(artifacts, "_story_md_dir", lambda: "/tmp/story")
    monkeypatch.setattr(artifacts, "_project_root", lambda: "/tmp/project")
    monkeypatch.setattr(artifacts, "_invalidate_stellar_home_render_cache", lambda: None)
    monkeypatch.setattr(artifacts, "_homepage_refresh_timeout_seconds", lambda: 30)

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(command, **kwargs):
        nonlocal active, max_active
        _ = command, kwargs
        with guard:
            active += 1
            max_active = max(max_active, active)
            entered.append(active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return Completed()

    monkeypatch.setattr(artifacts.subprocess, "run", _fake_run)

    threads = [
        threading.Thread(target=artifacts.refresh_stellar_homepage, args=("苏轼",)),
        threading.Thread(target=artifacts.refresh_stellar_homepage, args=("辛弃疾",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1
    assert entered
