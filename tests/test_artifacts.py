import sys
import json
import threading
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import artifacts


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
        [sys.executable, "tools/build_pep_people_spotlight.py"],
        [
            sys.executable,
            "tools/build_stellar_homepage.py",
            "--story-map-dir",
            "/tmp/story_map",
            "--story-md-dir",
            "/tmp/story",
        ],
    ]
