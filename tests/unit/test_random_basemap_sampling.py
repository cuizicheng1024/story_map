import importlib.util
import json
import sys
import types

from tests_support import REPO_ROOT
TOOLS_DIR = REPO_ROOT / "tools"

def _load_module():
    fake_playwright = types.ModuleType("playwright")
    fake_sync_api = types.ModuleType("playwright.sync_api")

    class _FakeTimeoutError(Exception):
        pass

    def _unused_sync_playwright():
        raise AssertionError("sync_playwright should not be used in this unit test")

    fake_sync_api.TimeoutError = _FakeTimeoutError
    fake_sync_api.sync_playwright = _unused_sync_playwright
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules["playwright.sync_api"] = fake_sync_api
    module_path = TOOLS_DIR / "test_random_basemaps.py"
    spec = importlib.util.spec_from_file_location("test_random_basemaps_tool", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def test_candidate_pages_keeps_sparse_single_site_profiles(tmp_path):
    tool = _load_module()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    html_path = artifacts_dir / "李春.html"
    payload = {
        "person": {"name": "李春"},
        "locations": [{"name": "赵州桥", "lng": 114.78, "lat": 37.76}],
    }
    html_path.write_text(
        "<html><body><script>const data = "
        + json.dumps(payload, ensure_ascii=False)
        + "; window.__EXPORT_DATA__ = data;</script></body></html>",
        encoding="utf-8",
    )

    candidates = tool._candidate_pages(artifacts_dir)

    assert len(candidates) == 1
    assert candidates[0]["person"] == "李春"
    assert candidates[0]["locations"] == 1

def test_single_site_sampling_uses_zero_focus_and_skips_segment_requirement():
    _load_module()
    source = (TOOLS_DIR / "test_random_basemaps.py").read_text(encoding="utf-8")

    assert "focus_index = 0 if int(item[\"locations\"]) <= 1 else max(1, int(item[\"locations\"]) // 2)" in source
    assert "return locationCount <= 1 ? true : segments.length > 0;" in source
