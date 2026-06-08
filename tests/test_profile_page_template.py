import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from map_html_renderer import render_profile_html


def test_render_profile_html_uses_external_template():
    html = render_profile_html(
        {
            "person": {"name": "测试人物", "description": "生平简介"},
            "locations": [],
            "highlights": {},
        }
    )

    assert "__TITLE__" not in html
    assert "__DATA__" not in html
    assert "测试人物的人生足迹地图" in html
    assert "window.__EXPORT_DATA__ = data;" in html
