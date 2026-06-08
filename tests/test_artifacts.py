import sys
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
