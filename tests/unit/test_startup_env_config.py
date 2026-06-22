

from tests_support import REPO_ROOT


def test_story_map_startup_does_not_override_existing_environment():
    content = (REPO_ROOT / "storymap" / "script" / "cli" / "story_map.py").read_text(encoding="utf-8")

    assert 'load_project_env(from_file=__file__, override=False)' in content
    assert 'load_project_env(from_file=__file__, override=True)' not in content
    assert 'strict=runtime_support_utils.strict_startup_enabled()' in content


def test_geocode_service_startup_does_not_override_existing_environment():
    content = (REPO_ROOT / "storymap" / "script" / "map" / "geocode_service.py").read_text(encoding="utf-8")

    assert 'load_project_env(from_file=__file__, override=False)' in content
    assert 'load_project_env(from_file=__file__, override=True)' not in content
