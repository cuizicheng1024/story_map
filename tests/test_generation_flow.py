import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import map_client
import story_map as sm


def test_generation_tools_expose_tool_metadata():
    geocode_tool = sm._GENERATION_TOOLS["geocode_markdown"]
    parse_tool = sm._GENERATION_TOOLS["parse_story_markdown"]
    validate_tool = sm._GENERATION_TOOLS["validate_story_markdown"]
    tool_names = {item["name"] for item in sm._GENERATION_TOOL_SPECS}

    assert geocode_tool.__tool__.name == "geocode_markdown"
    assert parse_tool.__tool__.name == "parse_story_markdown"
    assert validate_tool.__tool__.name == "validate_story_markdown"
    assert tool_names == {"geocode_markdown", "parse_story_markdown", "validate_story_markdown"}


def test_generate_for_person_can_render_existing_markdown_offline(tmp_path, monkeypatch):
    sample_md = REPO_ROOT / "storymap" / "examples" / "story" / "霍去病.md"
    out_html = tmp_path / "霍去病.html"
    refreshed = []

    monkeypatch.setattr(sm, "_story_paths", lambda person: (str(sample_md), str(out_html)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"places": [], "events": [], "points": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setitem(sm._GEOCODE_API, "resolve_place_coord", lambda *args, **kwargs: (34.3416, 108.9398))

    def _save_html(_person: str, content: str) -> str:
        out_html.write_text(content, encoding="utf-8")
        return str(out_html)

    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda person: refreshed.append(person) or {"ok": True, "person": person})
    monkeypatch.setattr(sm, "save_html", _save_html)

    result = sm.generate_for_person(client=None, person="霍去病", allow_cache=True)

    assert result["ok"] is True
    assert result["used_existing_markdown"] is True
    assert result["html_path"] == str(out_html)
    assert result["_state"]["person"] == "霍去病"
    assert result["_state"]["used_existing_markdown"] is True
    assert result["_state"]["stage"] == "build_profile"
    assert result["_homepage_refresh"]["ok"] is True
    assert refreshed == ["霍去病"]
    assert out_html.exists()

    html = out_html.read_text(encoding="utf-8")
    assert "霍去病" in html
    assert "河西走廊" in html


def test_generate_for_person_can_add_new_historical_person_end_to_end(tmp_path, monkeypatch):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    out_html = tmp_path / f"{person}.html"
    refreshed = []

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(out_html)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md + "\n\n## 地点坐标\n| 地点 | 纬度 | 经度 |\n| --- | --- | --- |\n| 黄冈 | 30.45 | 114.87 |\n")
    monkeypatch.setitem(
        sm._GENERATION_TOOLS,
        "parse_story_markdown",
        lambda _md: {
            "places": [{"ancient": "黄冈", "modern": "黄冈"}],
            "events": [{"year": "1889", "event": "出生"}],
            "points": [{"name": "黄冈", "lat": 30.45, "lng": 114.87}],
        },
    )
    monkeypatch.setitem(
        sm._GENERATION_TOOLS,
        "validate_story_markdown",
        lambda _md: {"metrics": {"timeline_rows": 1, "places": 1, "locations": 1, "coords": 1}, "issues": []},
    )
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, requested_person: (
            f"# {requested_person}\n\n"
            "## 一、人物简介\n"
            "- **出生**：湖北黄冈\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n"
        ),
    )
    monkeypatch.setattr(sm, "compute_total_distance_km", lambda _md: None)
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [{"name": "黄冈"}], "mapStyle": {}, "markdown": md},
    )

    def _save_markdown(_person: str, content: str) -> str:
        md_path.write_text(content, encoding="utf-8")
        return str(md_path)

    def _save_html(_person: str, content: str) -> str:
        out_html.write_text(content, encoding="utf-8")
        return str(out_html)

    monkeypatch.setattr(sm, "save_markdown", _save_markdown)
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{len(points)}|{md}</body></html>")
    monkeypatch.setattr(sm, "save_html", _save_html)
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: refreshed.append(requested_person) or {"ok": True, "person": requested_person})

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["ok"] is True
    assert result["person"] == person
    assert result["cached"] is False
    assert result["markdown_path"] == str(md_path)
    assert result["html_path"] == str(out_html)
    assert result["_homepage_refresh"] == {"ok": True, "person": person}
    assert result["_state"]["person"] == person
    assert result["_state"]["stage"] == "done"
    assert result["_state"]["quality_issues"] == []
    assert refreshed == [person]
    assert md_path.exists()
    assert out_html.exists()
    assert "地点坐标" in md_path.read_text(encoding="utf-8")
    assert person in out_html.read_text(encoding="utf-8")
    assert "黄冈" in out_html.read_text(encoding="utf-8")


def test_append_coords_section_skips_event_column_when_timeline_has_no_place_headers(monkeypatch):
    md = """## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| --- | --- | --- |
| 1900年 | 0岁 | 出生于北京 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda _name: (_ for _ in ()).throw(AssertionError("should not geocode event column")))

    assert map_client.append_coords_section(md) == md
