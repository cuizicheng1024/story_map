import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import artifacts


def test_active_story_map_dir_falls_back_to_legacy_when_artifact_has_no_index(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    legacy_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "index.html").write_text("<html>legacy</html>", encoding="utf-8")

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))
    monkeypatch.setattr(artifacts, "_legacy_story_map_dir", lambda: str(legacy_dir))

    assert artifacts._active_story_map_dir() == str(legacy_dir)


def test_public_story_map_dirs_keep_homepage_first_and_outputs_available(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "story_map"
    legacy_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "index.html").write_text("<html>legacy</html>", encoding="utf-8")

    monkeypatch.setattr(artifacts, "_story_artifacts_dir", lambda: str(artifact_dir))
    monkeypatch.setattr(artifacts, "_legacy_story_map_dir", lambda: str(legacy_dir))

    assert artifacts._public_story_map_dirs() == [str(legacy_dir), str(artifact_dir)]
