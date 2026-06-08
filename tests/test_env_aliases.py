import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from env_utils import apply_story_map_env_aliases


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
