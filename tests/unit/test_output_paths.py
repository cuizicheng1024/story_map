import importlib
import sys

from tests_support import REPO_ROOT

def _reload(module_name: str, *aliases: str):
    for name in (module_name, *aliases):
        sys.modules.pop(name, None)
    return importlib.import_module(module_name)

def test_build_all_defaults_to_artifacts_dir(monkeypatch):
    monkeypatch.delenv("MAP_STORY_OUTPUT_DIR", raising=False)

    module = _reload("tools.build.build_all", "tools.build_all")

    assert module.STORY_MAP_DIR == REPO_ROOT / "artifacts" / "story_map"
    assert module.HOME_DATA == REPO_ROOT / "artifacts" / "story_map" / "stellar_home_data.json"

def test_build_all_supports_relative_output_override(monkeypatch):
    monkeypatch.setenv("MAP_STORY_OUTPUT_DIR", "tmp/story-output")

    module = _reload("tools.build.build_all", "tools.build_all")

    assert module.STORY_MAP_DIR == REPO_ROOT / "tmp" / "story-output"

def test_build_stellar_homepage_supports_relative_output_override(monkeypatch):
    monkeypatch.setenv("MAP_STORY_OUTPUT_DIR", "tmp/home-output")

    module = _reload("tools.build.build_stellar_homepage", "tools.build_stellar_homepage")

    assert module.STORY_MAP_DIR == REPO_ROOT / "tmp" / "home-output"

def test_build_stellar_homepage_sync_vendor_assets(tmp_path, monkeypatch):
    module = _reload("tools.build.build_stellar_homepage", "tools.build_stellar_homepage")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    src_vendor = tmp_path / "vendor"
    src_vendor.mkdir()
    (src_vendor / "tailwindcss.js").write_text("console.log('ok');", encoding="utf-8")

    out_dir = tmp_path / "artifacts" / "story_map"
    out_dir.mkdir(parents=True)

    module._sync_vendor_assets(out_dir)

    assert (out_dir / "vendor" / "tailwindcss.js").read_text(encoding="utf-8") == "console.log('ok');"
