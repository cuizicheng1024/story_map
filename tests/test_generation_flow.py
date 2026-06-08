import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_map as sm


def test_generate_for_person_can_render_existing_markdown_offline(tmp_path, monkeypatch):
    sample_md = REPO_ROOT / "storymap" / "examples" / "story" / "霍去病.md"
    out_html = tmp_path / "霍去病.html"

    monkeypatch.setattr(sm, "_story_paths", lambda person: (str(sample_md), str(out_html)))
    monkeypatch.setattr(sm, "append_coords_section", lambda md: md)
    monkeypatch.setattr(sm, "build_points", lambda *args, **kwargs: [])
    monkeypatch.setattr(sm, "resolve_place_coord", lambda *args, **kwargs: (34.3416, 108.9398))

    def _save_html(_person: str, content: str) -> str:
        out_html.write_text(content, encoding="utf-8")
        return str(out_html)

    monkeypatch.setattr(sm, "save_html", _save_html)

    result = sm.generate_for_person(client=None, person="霍去病", allow_cache=True)

    assert result["ok"] is True
    assert result["used_existing_markdown"] is True
    assert result["html_path"] == str(out_html)
    assert out_html.exists()

    html = out_html.read_text(encoding="utf-8")
    assert "霍去病" in html
    assert "河西走廊" in html
