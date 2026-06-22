import os
import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.core.env_utils import apply_story_map_env_aliases
from storymap.script.runtime.support import collect_startup_issues, strict_startup_enabled


def test_apply_story_map_env_aliases_promotes_legacy_names(monkeypatch):
    monkeypatch.delenv("AMAP_KEY", raising=False)
    monkeypatch.delenv("AMAP_SECURITY", raising=False)
    monkeypatch.delenv("MAP_STORY_API_BASE", raising=False)
    monkeypatch.setenv("Amap_API_Key", "legacy-key")
    monkeypatch.setenv("Amap_API_Secret", "legacy-sec")
    monkeypatch.setenv("STORY_MAP_API_BASE", "http://legacy.example")

    apply_story_map_env_aliases()

    assert os.getenv("AMAP_KEY") == "legacy-key"
    assert os.getenv("AMAP_SECURITY") == "legacy-sec"
    assert os.getenv("MAP_STORY_API_BASE") == "http://legacy.example"


def test_collect_startup_issues_reports_missing_optional_keys(tmp_path, monkeypatch):
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    for key in [
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL_ID",
        "MINIMAX_API_KEY",
        "MINIMAX_BASE_URL",
        "MINIMAX_MODEL",
        "MIMO_API_KEY",
        "MIMO_BASE_URL",
        "MIMO_MODEL",
        "API_KEY",
        "BASE_URL",
        "MODEL",
        "AMAP_KEY",
        "AMAP_SECURITY",
        "location_api",
        "locaion_api",
        "LOCATION_API",
        "MAPSCO_API_KEY",
        "AMAP_WEBSERVICE_KEY",
        "AMAP_WEB_SERVICE_KEY",
        "AMAP_REST_KEY",
        "MONID_API_KEY",
        "MAP_STORY_MONID_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    issues = collect_startup_issues(str(tmp_path))

    assert issues["errors"] == []
    assert any("缺少大模型配置" in item for item in issues["warnings"])
    assert any("缺少 AMAP_KEY" in item for item in issues["warnings"])
    assert any("缺少地理编码密钥" in item for item in issues["warnings"])


def test_collect_startup_issues_accepts_monid_key_for_geocode(tmp_path, monkeypatch):
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    monkeypatch.setenv("MONID_API_KEY", "monid_live_test")
    for key in [
        "location_api",
        "locaion_api",
        "LOCATION_API",
        "MAPSCO_API_KEY",
        "AMAP_WEBSERVICE_KEY",
        "AMAP_WEB_SERVICE_KEY",
        "AMAP_REST_KEY",
        "MAP_STORY_MONID_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    issues = collect_startup_issues(str(tmp_path))

    assert not any("缺少地理编码密钥" in item for item in issues["warnings"])
    assert any("地理编码配置可用" in item for item in issues["notes"])


def test_collect_startup_issues_reports_missing_story_dir(tmp_path):
    issues = collect_startup_issues(str(tmp_path))

    assert any("缺少人物故事目录" in item for item in issues["errors"])


def test_strict_startup_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("STORY_MAP_STRICT_STARTUP", raising=False)
    monkeypatch.delenv("MAP_STORY_STRICT_STARTUP", raising=False)

    assert strict_startup_enabled() is True


def test_strict_startup_enabled_respects_explicit_false(monkeypatch):
    monkeypatch.setenv("STORY_MAP_STRICT_STARTUP", "0")

    assert strict_startup_enabled() is False
