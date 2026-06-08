import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_build_all_defaults_to_artifacts_dir(monkeypatch):
    monkeypatch.delenv("MAP_STORY_OUTPUT_DIR", raising=False)

    module = _reload("tools.build_all")

    assert module.STORY_MAP_DIR == REPO_ROOT / "artifacts" / "story_map"
    assert module.HOME_DATA == REPO_ROOT / "artifacts" / "story_map" / "stellar_home_data.json"


def test_build_all_supports_relative_output_override(monkeypatch):
    monkeypatch.setenv("MAP_STORY_OUTPUT_DIR", "tmp/story-output")

    module = _reload("tools.build_all")

    assert module.STORY_MAP_DIR == REPO_ROOT / "tmp" / "story-output"


def test_build_stellar_homepage_supports_relative_output_override(monkeypatch):
    monkeypatch.setenv("MAP_STORY_OUTPUT_DIR", "tmp/home-output")

    module = _reload("tools.build_stellar_homepage")

    assert module.STORY_MAP_DIR == REPO_ROOT / "tmp" / "home-output"
