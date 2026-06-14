from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_story_map_startup_does_not_override_existing_environment():
    content = (REPO_ROOT / "storymap" / "script" / "story_map.py").read_text(encoding="utf-8")

    assert 'load_project_env(from_file=__file__, override=False)' in content
    assert 'load_project_env(from_file=__file__, override=True)' not in content


def test_geocode_service_startup_does_not_override_existing_environment():
    content = (REPO_ROOT / "storymap" / "script" / "geocode_service.py").read_text(encoding="utf-8")

    assert 'load_project_env(from_file=__file__, override=False)' in content
    assert 'load_project_env(from_file=__file__, override=True)' not in content
