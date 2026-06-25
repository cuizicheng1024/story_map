import os
import sys
import time
from pathlib import Path

from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.agent import generation_service
from storymap.script.agent.generation_pipeline import (
    FileGenerationCheckpointStore,
    GenerationStages,
    build_generation_checkpoint,
)
from storymap.script.agent import registry as story_agents
from storymap.script.cli import interactive as story_cli
from storymap.script.cli import story_map as sm
from storymap.script.map import map_client
from storymap.script.runtime import support as runtime_support


def _run_background_job_inline(job, **_kwargs):
    return job()


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
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)
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


def test_render_html_builds_profile_without_online_geocode():
    calls = []

    def _build_profile_data(md, **kwargs):
        calls.append({"md": md, **kwargs})
        return {"person": {"name": "蒙恬"}, "locations": []}

    html = generation_service.render_html(
        "蒙恬",
        [],
        md="# 蒙恬",
        build_profile_data=_build_profile_data,
        extract_intro_fields=lambda _md: {},
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        build_info_panel_html=lambda title, fields: f"{title}|{fields}",
        render_amap_html=lambda title, points, info_html: f"{title}|{len(points)}|{info_html}",
    )

    assert html == "<html>蒙恬</html>"
    assert calls == [{"md": "# 蒙恬", "fallback_person": "蒙恬", "allow_geocode": False}]


def test_generate_for_person_refreshes_cached_html_when_markdown_is_newer(tmp_path, monkeypatch):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    html_path.write_text(
        '<html><body><script>const data = {"person":{"name":"霍去病"},"locations":[]}; window.__EXPORT_DATA__ = data;</script>OLD</body></html>',
        encoding="utf-8",
    )
    time.sleep(0.01)
    md_path.write_text("# 霍去病\n\nNEW_MARKDOWN\n", encoding="utf-8")

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(html_path)))
    monkeypatch.setattr(sm, "load_profile_from_md", lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md})
    monkeypatch.setattr(sm, "render_profile_html", lambda profile: f"<html><body>{profile.get('markdown','')}</body></html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: {"ok": True, "person": requested_person})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=None, person=person, allow_cache=True)

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert "NEW_MARKDOWN" in html_path.read_text(encoding="utf-8")
    assert "OLD" not in html_path.read_text(encoding="utf-8")


def test_render_html_uses_title_as_profile_name_fallback():
    html = generation_service.render_html(
        "李四光",
        [],
        md="## 地点坐标\n| 现称 | 纬度 | 经度 |\n| --- | --- | --- |\n| 湖北黄冈 | 30.45 | 114.87 |\n",
        build_profile_data=lambda md, fallback_person="", **_kwargs: {
            "person": {"name": fallback_person},
            "locations": [],
            "highlights": {},
        },
        extract_intro_fields=lambda _md: {},
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        build_info_panel_html=lambda title, fields: f"{title}|{fields}",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{info_html}</html>",
    )

    assert html == "<html>李四光</html>"


def test_generate_for_person_rebuilds_when_cached_export_data_is_empty(tmp_path):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 霍去病\n\nNEW_MARKDOWN\n", encoding="utf-8")
    html_path.write_text(
        '<html><body><script>const data = {}; window.__EXPORT_DATA__ = data;</script>OLD</body></html>',
        encoding="utf-8",
    )

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html><body>{profile['person']['name']}|{profile.get('markdown', '')}</body></html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert result["_profile"]["person"]["name"] == person
    assert result["_profile"]["markdown"] == "# 霍去病\n\nNEW_MARKDOWN\n"


def test_generate_for_person_rebuilds_when_cached_export_data_lacks_person_name(tmp_path):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 霍去病\n\nNEW_MARKDOWN\n", encoding="utf-8")
    html_path.write_text(
        '<html><body><script>const data = {"person":{},"locations":[{"name":"河西走廊"}]}; window.__EXPORT_DATA__ = data;</script>OLD</body></html>',
        encoding="utf-8",
    )

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {}, "locations": [{"name": "河西走廊"}]},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html><body>{profile['person']['name']}|{profile.get('markdown', '')}</body></html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [{"name": "河西走廊"}], "mapStyle": {}, "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert result["_profile"]["person"]["name"] == person
    assert result["_profile"]["locations"] == [{"name": "河西走廊"}]


def test_generate_for_person_hits_cache_for_new_runtime_config_loader_html(tmp_path):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 霍去病\n\nNEW_MARKDOWN\n", encoding="utf-8")
    html_path.write_text(
        '<html><head><script src="./amap-config.js"></script><script src="./geovis-config.js"></script></head>'
        '<body><script>const data = {"person":{"name":"霍去病"},"locations":[]}; window.__EXPORT_DATA__ = data;</script>OLD</body></html>',
        encoding="utf-8",
    )
    (tmp_path / "amap-config.js").write_text("window.AMAP_KEY='x';", encoding="utf-8")
    (tmp_path / "geovis-config.js").write_text("window.GEOVIS_TOKEN='y';", encoding="utf-8")

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": person}, "locations": []},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: (_ for _ in ()).throw(AssertionError("cache hit should not re-render html")),
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result.get("refreshed") is not True
    assert html_path.read_text(encoding="utf-8").endswith("OLD</body></html>")


def test_generate_for_person_refreshes_cache_when_geovis_loader_is_missing(tmp_path):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 霍去病\n\nNEW_MARKDOWN\n", encoding="utf-8")
    html_path.write_text(
        '<html><head><script src="./amap-config.js"></script></head>'
        '<body><script>const data = {"person":{"name":"霍去病"},"locations":[]}; window.__EXPORT_DATA__ = data;</script>OLD</body></html>',
        encoding="utf-8",
    )

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": person}, "locations": []},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html><body>{profile.get('markdown','')}|GEOVIS</body></html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert "GEOVIS" in html_path.read_text(encoding="utf-8")


def test_generate_for_person_can_add_new_historical_person_end_to_end(tmp_path, monkeypatch):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    out_html = tmp_path / f"{person}.html"
    refreshed = []
    client = type("DummyClient", (), {})()

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
            setattr(
                _client,
                "last_agent_runtime",
                {
                    "person": requested_person,
                    "max_llm_calls": 4,
                    "langgraph_available": True,
                    "tool_specs": [{"name": "search_person_info"}],
                    "state": {
                        "llm_calls_used": 2,
                        "llm_calls_limit": 4,
                        "degraded_reasons": [],
                        "execution_trace": ["supervisor", "search_agent", "editor_agent", "critic_agent"],
                        "tool_traces": [{"tool_name": "search_person_info"}],
                        "memory_hits": {"search": 1},
                        "memory_misses": {"place_map": 1},
                    },
                },
            )
            or (
                f"# {requested_person}\n\n"
                "## 一、人物简介\n"
                "- **出生**：湖北黄冈\n\n"
                "## 四、生平时间线\n\n"
                "| 年份 | 古称 | 现称 | 事件 |\n"
                "| --- | --- | --- | --- |\n"
                "| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n"
            )
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
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=client, person=person, allow_cache=False)

    assert result["ok"] is True
    assert result["person"] == person
    assert result["cached"] is False
    assert result["markdown_path"] == str(md_path)
    assert result["html_path"] == str(out_html)
    assert result["_homepage_refresh"] == {"ok": True, "person": person}
    assert result["_state"]["person"] == person
    assert result["_state"]["stage"] == "done"
    assert result["_state"]["quality_issues"] == []
    assert result["_agent_runtime"]["state"]["llm_calls_used"] == 2
    assert result["_agent_runtime"]["state"]["execution_trace"] == ["supervisor", "search_agent", "editor_agent", "critic_agent"]
    assert result["_agent_runtime"]["state"]["tool_traces"] == [{"tool_name": "search_person_info"}]
    assert result["_agent_runtime"]["state"]["memory_hits"] == {"search": 1}
    assert result["_agent_runtime"]["state"]["memory_misses"] == {"place_map": 1}
    assert result["_agent_runtime"]["state"]["validation"]["issues"] == []
    assert result["_agent_runtime"]["state"]["validation"]["metrics"]["coords"] == 1
    assert result["_agent_runtime"]["state"]["validation_stage"] == "final_output"
    assert result["_state"]["agent_runtime"]["state"]["llm_calls_limit"] == 4
    assert result["_state"]["agent_runtime"]["tool_specs"] == [{"name": "search_person_info"}]
    assert refreshed == [person]
    assert md_path.exists()
    assert out_html.exists()
    assert "地点坐标" in md_path.read_text(encoding="utf-8")
    assert person in out_html.read_text(encoding="utf-8")
    assert "黄冈" in out_html.read_text(encoding="utf-8")


def test_story_map_generate_for_person_canonicalizes_alias_request(tmp_path, monkeypatch):
    requested_person = "苏东坡"
    canonical_person = "苏轼"
    md_path = tmp_path / f"{canonical_person}.md"
    out_html = tmp_path / f"{canonical_person}.html"
    refreshed = []
    generated = []

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(out_html)))
    monkeypatch.setattr(sm, "story_person_names", lambda _dir: [canonical_person])
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"places": [], "events": [], "points": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, person: generated.append(person) or f"# {person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 1037年 | 眉州眉山 | 四川眉山 | 出生 |\n",
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": canonical_person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "save_markdown", lambda _person, content: (md_path.write_text(content, encoding="utf-8"), str(md_path))[1])
    monkeypatch.setattr(sm, "save_html", lambda _person, content: (out_html.write_text(content, encoding="utf-8"), str(out_html))[1])
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{md}</body></html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda person: refreshed.append(person) or {"ok": True, "person": person})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person=requested_person, allow_cache=False)

    assert result["ok"] is True
    assert result["person"] == canonical_person
    assert result["requested_person"] == requested_person
    assert result["markdown_path"] == str(md_path)
    assert result["html_path"] == str(out_html)
    assert generated == [canonical_person]
    assert refreshed == [canonical_person]
    assert result["_state"]["person"] == canonical_person
    assert result["_state"]["requested_person"] == requested_person


def test_story_map_generate_for_person_preserves_alias_when_alias_is_real_story_source(tmp_path, monkeypatch):
    requested_person = "苏东坡"
    md_path = tmp_path / f"{requested_person}.md"
    out_html = tmp_path / f"{requested_person}.html"
    refreshed = []
    generated = []

    monkeypatch.setattr(sm, "_story_paths", lambda person: (str(tmp_path / f"{person}.md"), str(tmp_path / f"{person}.html")))
    monkeypatch.setattr(sm, "story_person_names", lambda _dir: ["苏轼", "苏东坡"])
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"places": [], "events": [], "points": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, person: generated.append(person) or f"# {person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 1037年 | 眉州眉山 | 四川眉山 | 出生 |\n",
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": requested_person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "save_markdown", lambda person, content: ((tmp_path / f"{person}.md").write_text(content, encoding="utf-8"), str(tmp_path / f"{person}.md"))[1])
    monkeypatch.setattr(sm, "save_html", lambda person, content: ((tmp_path / f"{person}.html").write_text(content, encoding="utf-8"), str(tmp_path / f"{person}.html"))[1])
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{md}</body></html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda person: refreshed.append(person) or {"ok": True, "person": person})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person=requested_person, allow_cache=False)

    assert result["ok"] is True
    assert result["person"] == requested_person
    assert result["requested_person"] == requested_person
    assert result["markdown_path"] == str(md_path)
    assert result["html_path"] == str(out_html)
    assert generated == [requested_person]
    assert refreshed == [requested_person]


def test_generate_for_person_inserts_distance_intro_after_geocoding(tmp_path, monkeypatch):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    out_html = tmp_path / f"{person}.html"

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(out_html)))
    monkeypatch.setitem(
        sm._GENERATION_TOOLS,
        "geocode_markdown",
        lambda md: md
        + "\n\n## 地点坐标（自动地理编码）\n"
        + "| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |\n"
        + "| --- | --- | --- | --- | --- |\n"
        + "| 黄冈 | 湖北黄冈 | 30.45 | 114.87 | WGS84 |\n"
        + "| 北京 | 北京 | 39.90 | 116.40 | WGS84 |\n",
    )
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"places": [], "events": [], "points": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, requested_person: (
            f"# {requested_person}\n\n"
            "## 二、人生足迹地图说明\n"
            "- 🌟 **重要节点数量**：2 个\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n"
            "| 1910年 | 北京 | 北京 | 求学 |\n"
        ),
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
    )

    def _save_markdown(_person: str, content: str) -> str:
        md_path.write_text(content, encoding="utf-8")
        return str(md_path)

    def _save_html(_person: str, content: str) -> str:
        out_html.write_text(content, encoding="utf-8")
        return str(out_html)

    monkeypatch.setattr(sm, "save_markdown", _save_markdown)
    monkeypatch.setattr(sm, "save_html", _save_html)
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{md}</body></html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: {"ok": True, "person": requested_person})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["ok"] is True
    saved_md = md_path.read_text(encoding="utf-8")
    assert "总行程估算" in saved_md
    assert "地点坐标（自动地理编码）" in saved_md
    assert "| 坐标系 |" in saved_md
    assert "WGS84" in saved_md


def test_generate_for_person_marks_render_failure_as_degraded_when_reusing_markdown(tmp_path):
    person = "王昭君"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 王昭君\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 前54年 | 南郡秭归 | 湖北秭归 | 出生 |\n", encoding="utf-8")

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: (_ for _ in ()).throw(RuntimeError("boom")),
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["used_existing_markdown"] is True
    assert result["fallback_html_path"] == str(html_path)
    assert result["render_error"] == "boom"


def test_generate_for_person_marks_render_failure_as_degraded_for_new_generation(tmp_path):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"

    result = generation_service.generate_for_person(
        client=object(),
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: (_ for _ in ()).throw(RuntimeError("render failed")),
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["fallback_html_path"] == str(html_path)
    assert result["render_error"] == "render failed"


def test_generate_for_person_loads_profile_without_online_geocode_for_new_generation(tmp_path):
    person = "蒙恬"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    load_calls = []

    result = generation_service.generate_for_person(
        client=object(),
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **kwargs: load_calls.append({"md": md, **kwargs}) or {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 前221年 | 咸阳 | 陕西咸阳 | 出生 |\n",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert load_calls
    assert load_calls[-1]["fallback_person"] == person
    assert load_calls[-1]["allow_geocode"] is False


def test_generate_for_person_marks_quality_issues_as_degraded_when_reusing_markdown(tmp_path):
    person = "王昭君"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text("# 王昭君\n\n## 一、人物简介\n\n- **出生**：南郡秭归\n", encoding="utf-8")

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": ["重要地点段落缺失或为空"]},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["used_existing_markdown"] is True
    assert result["html_path"] == str(html_path)
    assert result["quality_issue_summary"] == "重要地点段落缺失或为空"


def test_generate_for_person_marks_quality_issues_as_degraded_for_new_generation(tmp_path):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"

    result = generation_service.generate_for_person(
        client=object(),
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": ["地点坐标表缺失或为空"]},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["html_path"] == str(html_path)
    assert result["markdown_path"] == str(md_path)
    assert result["quality_issue_summary"] == "地点坐标表缺失或为空"
    assert result["_validation"]["issues"] == ["地点坐标表缺失或为空"]


def test_story_map_wrapper_refreshes_homepage_for_degraded_result(tmp_path, monkeypatch):
    person = "王昭君"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    refreshed = []
    md_path.write_text(
        "# 王昭君\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 前54年 | 南郡秭归 | 湖北秭归 | 出生 |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(html_path)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "render_amap_html", lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: refreshed.append(requested_person) or {"ok": True})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=None, person=person, allow_cache=True)

    assert result["status"] == "degraded"
    assert result["_state"]["stage"] == "build_profile"
    assert result["_homepage_refresh"] == {"ok": True}
    assert refreshed == [person]


def test_story_map_wrapper_preserves_quality_degraded_result_as_usable(tmp_path, monkeypatch):
    person = "王昭君"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    refreshed = []

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(html_path)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": ["重要地点段落缺失或为空"]})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"points": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, requested_person: f"# {requested_person}\n\n## 一、人物简介\n\n- **出生**：南郡秭归\n",
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{md}</body></html>")
    monkeypatch.setattr(sm, "save_markdown", lambda _person, content: (md_path.write_text(content, encoding="utf-8"), str(md_path))[1])
    monkeypatch.setattr(sm, "save_html", lambda _person, content: (html_path.write_text(content, encoding="utf-8"), str(html_path))[1])
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: refreshed.append(requested_person) or {"ok": True})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["status"] == "degraded"
    assert result["_state"]["stage"] == "done"
    assert result["_state"]["quality_issues"] == ["重要地点段落缺失或为空"]
    assert result["_homepage_refresh"] == {"ok": True}
    assert refreshed == [person]


def test_story_map_wrapper_marks_homepage_refresh_failure_as_degraded(tmp_path, monkeypatch):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(html_path)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"points": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 前140年 | 平阳 | 山西临汾 | 出生 |\n",
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "save_markdown", lambda _person, content: (md_path.write_text(content, encoding="utf-8"), str(md_path))[1])
    monkeypatch.setattr(sm, "save_html", lambda _person, content: (html_path.write_text(content, encoding="utf-8"), str(html_path))[1])
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{md}</body></html>")
    monkeypatch.setattr(
        sm,
        "refresh_stellar_homepage",
        lambda requested_person: {"ok": False, "person": requested_person, "returncode": 124, "output": "timeout"},
    )
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["homepage_refresh_failed"] is True
    assert result["homepage_refresh_error"] == "timeout"
    assert "首页刷新失败" in result["error"]
    assert result["_homepage_refresh"]["ok"] is False


def test_story_map_wrapper_schedules_homepage_refresh_in_background(tmp_path, monkeypatch):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    refreshed = []
    queued = []

    monkeypatch.setattr(sm, "_story_paths", lambda _person: (str(md_path), str(html_path)))
    monkeypatch.setitem(sm._GENERATION_TOOLS, "geocode_markdown", lambda md: md)
    monkeypatch.setitem(sm._GENERATION_TOOLS, "validate_story_markdown", lambda _md: {"metrics": {}, "issues": []})
    monkeypatch.setitem(sm._GENERATION_TOOLS, "parse_story_markdown", lambda _md: {"points": []})
    monkeypatch.setattr(
        sm,
        "generate_historical_markdown",
        lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 前140年 | 平阳 | 山西临汾 | 出生 |\n",
    )
    monkeypatch.setattr(
        sm,
        "load_profile_from_md",
        lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "mapStyle": {}, "markdown": md},
    )
    monkeypatch.setattr(sm, "save_markdown", lambda _person, content: (md_path.write_text(content, encoding="utf-8"), str(md_path))[1])
    monkeypatch.setattr(sm, "save_html", lambda _person, content: (html_path.write_text(content, encoding="utf-8"), str(html_path))[1])
    monkeypatch.setattr(sm, "render_html", lambda title, points, md="": f"<html><body>{title}|{md}</body></html>")
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda requested_person: refreshed.append(requested_person) or {"ok": True})
    monkeypatch.setattr(sm, "_enqueue_background_job", lambda job, **kwargs: queued.append(kwargs) or True)

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["ok"] is True
    assert result["homepage_refresh_scheduled"] is True
    assert result["_homepage_refresh"]["state"] == "queued"
    assert result["_homepage_refresh"]["async"] is True
    assert result["_state"]["homepage_refresh_state"] == "queued"
    assert refreshed == []
    assert queued
    assert queued[0]["label"] == f"homepage-refresh:{person}"


def test_generate_for_person_marks_runtime_config_write_failure_as_degraded(tmp_path):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"

    result = generation_service.generate_for_person(
        client=object(),
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, requested_person: f"# {requested_person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
        build_amap_config_js=lambda: (_ for _ in ()).throw(RuntimeError("amap config failed")),
        build_geovis_config_js=lambda: b"window.GEOVIS_TOKEN='x';",
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["runtime_config_failed"] is True
    assert result["runtime_config_error"] == "amap config failed"
    assert "运行时地图配置写入失败" in result["error"]


def test_generate_for_person_retries_retryable_markdown_failure_once(tmp_path):
    person = "李四光"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    attempts = []

    class _Client:
        def __init__(self):
            self._trace = {}
            self.last_agent_runtime = {}

        def latest_trace(self):
            return dict(self._trace)

    client = _Client()

    def _generate_markdown(_client, requested_person):
        attempts.append(requested_person)
        if len(attempts) == 1:
            client._trace = {"classification": "rate_limit", "retryable": True, "error": "HTTP 429"}
            return ""
        client._trace = {"classification": "ok", "retryable": False}
        return (
            f"# {requested_person}\n\n## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1889年 | 黄冈 | 湖北黄冈 | 出生 |\n"
        )

    result = generation_service.generate_for_person(
        client=client,
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: client,
        generate_historical_markdown=_generate_markdown,
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert attempts == [person, person]
    assert result["retry_count"] == 1
    assert result["stage"] == "done"
    assert result["checkpoint"]["source"] == "generated_markdown"
    assert result["checkpoint"]["resume_stage"] == "markdown_saved"


def test_generate_for_person_exposes_non_retryable_markdown_failure(tmp_path):
    person = "霍去病"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"

    class _Client:
        def __init__(self):
            self._trace = {"classification": "auth", "retryable": False, "error": "HTTP 401"}
            self.last_agent_runtime = {}

        def latest_trace(self):
            return dict(self._trace)

    client = _Client()

    result = generation_service.generate_for_person(
        client=client,
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: client,
        generate_historical_markdown=lambda _client, _requested_person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is False
    assert result["stage"] == "markdown_generation"
    assert result["retry_count"] == 0
    assert result["error_classification"] == "auth"
    assert result["error_retryable"] is False
    assert result["checkpoint"]["source"] == "none"
    assert result["checkpoint"]["resume_stage"] == "start"


def test_generate_for_person_resumes_from_checkpoint_store_when_allow_cache_disabled(tmp_path):
    person = "李白"
    md_path = tmp_path / f"{person}.md"
    html_path = tmp_path / f"{person}.html"
    md_path.write_text(
        f"# {person}\n\n## 四、生平时间线\n\n| 年份 | 古称 | 现称 | 事件 |\n| --- | --- | --- | --- |\n| 701年 | 绥州 | 四川江油 | 出生 |\n",
        encoding="utf-8",
    )
    store = FileGenerationCheckpointStore(str(tmp_path / "generation_checkpoints.json"))
    store.save(
        person,
        stage=GenerationStages.RENDERING,
        checkpoint=build_generation_checkpoint(source="generated_markdown", resume_stage="markdown_saved"),
        retry_count=1,
        ok=False,
    )

    result = generation_service.generate_for_person(
        client=None,
        person=person,
        allow_cache=False,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": person}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: (Path(md_path).write_text(content, encoding="utf-8"), str(md_path))[1],
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: (Path(html_path).write_text(html, encoding="utf-8"), str(html_path))[1],
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _requested_person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
        checkpoint_store=store,
    )

    saved_state = store.load(person)

    assert result["ok"] is True
    assert result["used_existing_markdown"] is True
    assert result["stage"] == "build_profile"
    assert result["checkpoint"]["source"] == "checkpoint_store"
    assert result["checkpoint"]["resume_stage"] == "markdown_saved"
    assert saved_state["stage"] == "build_profile"
    assert saved_state["checkpoint"]["source"] == "checkpoint_store"
    assert saved_state["checkpoint"]["resume_stage"] == "markdown_saved"
    assert saved_state["ok"] is True


def test_story_map_wrapper_passes_checkpoint_store_into_generation_service(monkeypatch):
    captured = {}

    def _fake_generate_for_person(client, person, **kwargs):
        captured["client"] = client
        captured["person"] = person
        captured["checkpoint_store"] = kwargs.get("checkpoint_store")
        return {
            "ok": True,
            "person": person,
            "markdown_path": "",
            "html_path": f"/tmp/{person}.html",
            "_profile": {"person": {"name": person}, "locations": [], "mapStyle": {}},
        }

    monkeypatch.setattr(sm.generation_service_utils, "generate_for_person", _fake_generate_for_person)
    monkeypatch.setattr(sm, "refresh_stellar_homepage", lambda person: {"ok": True, "person": person})
    monkeypatch.setattr(sm, "_enqueue_background_job", _run_background_job_inline)

    result = sm.generate_for_person(client=object(), person="李白", allow_cache=False)

    assert result["ok"] is True
    assert captured["person"] == "李白"
    assert captured["checkpoint_store"].__class__.__name__ == "FileGenerationCheckpointStore"
    assert hasattr(captured["checkpoint_store"], "load")
    assert hasattr(captured["checkpoint_store"], "save")


def test_should_refresh_stellar_home_when_homepage_artifacts_are_missing(tmp_path):
    html_path = tmp_path / "霍去病.html"
    html_path.write_text("<html></html>", encoding="utf-8")

    result = sm._GENERATION_API["should_refresh_stellar_home"](
        {
            "ok": True,
            "person": "霍去病",
            "html_path": str(html_path),
            "cached": True,
            "refreshed": False,
        }
    )

    assert result is True


def test_should_skip_refresh_when_cached_result_has_homepage_artifacts(tmp_path):
    html_path = tmp_path / "霍去病.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (tmp_path / "stellar_home_data.json").write_text("{}", encoding="utf-8")

    result = sm._GENERATION_API["should_refresh_stellar_home"](
        {
            "ok": True,
            "person": "霍去病",
            "html_path": str(html_path),
            "cached": True,
            "refreshed": False,
        }
    )

    assert result is False


def test_run_person_generation_treats_degraded_output_as_usable(capsys):
    story_cli.run_person_generation(
        person_text="霍去病",
        create_client=lambda: object(),
        validate_input_text=lambda _text: None,
        resolve_targets=lambda _client, _text, _fallback: ["霍去病"],
        generate_for_person=lambda _client, _person: {
            "ok": False,
            "status": "degraded",
            "person": "霍去病",
            "markdown_path": "/tmp/霍去病.md",
            "html_path": "/tmp/霍去病.html",
            "duration": {"markdown": "0.10s", "geocode": "0.20s", "render": "0.30s", "total": "0.60s"},
        },
    )

    out = capsys.readouterr().out
    assert "已生成（降级）：霍去病" in out
    assert "未取得：霍去病" not in out
    assert "失败 0" in out


def test_run_interactive_marks_quality_degraded_output(capsys, monkeypatch):
    inputs = iter(["霍去病", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    story_cli.run_interactive(
        create_client=lambda: object(),
        validate_input_text=lambda _text: None,
        resolve_targets=lambda _client, _text, _fallback: ["霍去病"],
        generate_historical_markdown=lambda _client, person: f"# {person}\n",
        enrich_markdown_for_map=lambda md: md,
        validate_data_quality=lambda _md: ["重要地点段落缺失或为空"],
        print_quality_report=lambda _md: None,
        save_markdown=lambda person, _md: f"/tmp/{person}.md",
        parse_places=lambda _md: [],
        parse_events=lambda _md: [],
        build_points=lambda *_args, **_kwargs: [],
        render_html=lambda title, points, md: f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|fallback|{len(points)}|{info_html}</html>",
        save_html=lambda person, _html: f"/tmp/{person}.html",
        format_seconds=lambda _sec: "0.00s",
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    out = capsys.readouterr().out
    assert "已生成（降级）：/tmp/霍去病.md" in out
    assert "重要地点段落缺失或为空" in out
    assert "失败 0" in out


def test_build_conclusion_counts_degraded_results_as_success():
    results = [
        {"ok": False, "status": "degraded", "person": "霍去病"},
        {"ok": False, "person": "杜甫", "error": "no data"},
    ]

    assert runtime_support.build_conclusion(results, multi=False) == "生成完成：人物 1，失败 1"
    assert runtime_support.build_conclusion(results, multi=True) == "合并视图完成：人物 1，失败 1"


def test_append_coords_section_skips_event_column_when_timeline_has_no_place_headers(monkeypatch):
    md = """## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| --- | --- | --- |
| 1900年 | 0岁 | 出生于北京 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda _name: (_ for _ in ()).throw(AssertionError("should not geocode event column")))

    assert map_client.append_coords_section(md) == md


def test_append_coords_section_removes_stale_auto_coords_when_no_place_columns(monkeypatch):
    md = """## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| --- | --- | --- |
| 1037年 | 1岁 | 出生于眉州眉山 |

## 地点坐标（自动地理编码）
| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |
| --- | --- | --- | --- | --- |
| 出生于眉州眉山 | 出生于眉州眉山 | 39.913704 | 116.362106 | WGS84 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda _name: (_ for _ in ()).throw(AssertionError("should not geocode event column")))

    result = map_client.append_coords_section(md)

    assert "地点坐标（自动地理编码）" not in result
    assert "39.913704" not in result


def test_append_coords_section_rebuilds_existing_auto_coords_section(monkeypatch):
    md = """## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 1037年 | 眉州眉山 | 四川省眉山市东坡区 | 出生 |

## 地点坐标（自动地理编码）
| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |
| --- | --- | --- | --- | --- |
| 四川省眉山市东坡区 | 四川省眉山市东坡区 | 39.913704 | 116.362106 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda name: (30.0483, 103.8318) if "眉山" in name else None)

    result = map_client.append_coords_section(md)

    assert result.count("## 地点坐标（自动地理编码）") == 1
    assert "30.048300 | 103.831800" in result
    assert "39.913704" not in result


def test_append_coords_section_reuses_valid_existing_auto_coords_section(monkeypatch):
    md = """## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 1037年 | 眉州眉山 | 四川省眉山市东坡区 | 出生 |

## 地点坐标（自动地理编码）
| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |
| --- | --- | --- | --- | --- |
| 四川省眉山市东坡区 | 四川省眉山市东坡区 | 30.048300 | 103.831800 | WGS84 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda _name: (_ for _ in ()).throw(AssertionError("should reuse existing coords")))

    assert map_client.append_coords_section(md) == md


def test_compute_total_distance_km_supports_auto_generated_coords_table():
    md = """## 地点坐标（自动地理编码）
| 现称 | 现代搜索地名 | 纬度 | 经度 | 坐标系 |
| --- | --- | --- | --- | --- |
| 黄州 | 湖北黄冈 | 30.45 | 114.87 | WGS84 |
| 惠州 | 广东惠州 | 23.08 | 114.41 | WGS84 |
"""

    total = map_client.compute_total_distance_km(md)

    assert isinstance(total, float)
    assert total > 0


def test_enrich_markdown_for_map_runs_shared_pipeline_once():
    calls = []

    def _normalize(md):
        calls.append("normalize")
        return md + "\nN"

    def _geocode(md):
        calls.append("geocode")
        return md + "\n## 地点坐标\n| 地点 | 纬度 | 经度 |\n| --- | --- | --- |\n| 黄冈 | 30.45 | 114.87 |\n| 北京 | 39.90 | 116.40 |\n"

    def _compute(md):
        calls.append("compute")
        assert "地点坐标" in md
        return 123.0

    def _insert(md, km):
        calls.append(f"insert:{km}")
        return md + f"\n总里程={km}"

    enriched = generation_service.enrich_markdown_for_map(
        "# 测试",
        normalize_markdown_tables=_normalize,
        geocode_markdown=_geocode,
        compute_total_distance_km=_compute,
        insert_distance_intro=_insert,
    )

    assert calls == ["normalize", "geocode", "compute", "insert:123.0"]
    assert "总里程=123.0" in enriched


def test_enrich_markdown_for_map_normalizes_basic_info_birth_fields_before_geocode():
    seen = {}

    def _geocode(md):
        seen["markdown"] = md
        return md

    enriched = generation_service.enrich_markdown_for_map(
        "# 柏拉图\n\n## 一、人物档案\n\n### 基本信息\n- **出生**：约公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）\n",
        normalize_markdown_tables=lambda md: md,
        geocode_markdown=_geocode,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
    )

    assert enriched == seen["markdown"]
    assert "- **出生**：公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）" in enriched


def test_generate_for_person_refreshes_cached_html_when_code_dependency_is_newer(tmp_path):
    md_path = tmp_path / "诸葛亮.md"
    html_path = tmp_path / "诸葛亮.html"
    dep_path = tmp_path / "profile_builder.py"

    md_path.write_text("# 诸葛亮\n\n## 一、人物档案\n", encoding="utf-8")
    html_path.write_text(
        "<script>const data = {\"person\":{\"name\":\"旧诸葛亮\"}};\nwindow.__EXPORT_DATA__ = data;</script>",
        encoding="utf-8",
    )
    dep_path.write_text("# newer dependency\n", encoding="utf-8")
    os.utime(html_path, (1, 1))
    os.utime(dep_path, (2, 2))

    def _load_profile(md, **_kwargs):
        return {"person": {"name": "新诸葛亮"}, "locations": [], "mapStyle": {}, "markdown": md}

    result = generation_service.generate_for_person(
        client=None,
        person="诸葛亮",
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": "旧诸葛亮"}},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=_load_profile,
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[str(dep_path)],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert result["_profile"]["person"]["name"] == "新诸葛亮"


def test_generate_for_person_refreshes_cached_html_when_template_signature_is_stale(tmp_path):
    md_path = tmp_path / "诸葛亮.md"
    html_path = tmp_path / "诸葛亮.html"

    md_path.write_text("# 诸葛亮\n\n## 一、人物档案\n", encoding="utf-8")
    html_path.write_text(
        (
            '<script>const data = {"person":{"name":"旧诸葛亮"},"templateSignature":"old-sign"};\n'
            "window.__EXPORT_DATA__ = data;</script>\n"
            '<script src="/amap-config.js"></script>\n'
            '<script src="/geovis-config.js"></script>'
        ),
        encoding="utf-8",
    )
    os.utime(md_path, (1, 1))
    os.utime(html_path, (2, 2))

    def _load_profile(md, **_kwargs):
        return {"person": {"name": "新诸葛亮"}, "locations": [], "mapStyle": {}, "markdown": md}

    result = generation_service.generate_for_person(
        client=None,
        person="诸葛亮",
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": "旧诸葛亮"}},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=_load_profile,
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
        current_profile_signature=lambda: "new-sign",
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert result["_profile"]["person"]["name"] == "新诸葛亮"


def test_generate_for_person_writes_runtime_map_config_files_next_to_html(tmp_path):
    md_path = tmp_path / "关羽.md"
    html_path = tmp_path / "关羽.html"
    md_path.write_text("# 关羽\n\n## 一、人物档案\n", encoding="utf-8")

    result = generation_service.generate_for_person(
        client=None,
        person="关羽",
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": "旧关羽"}},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": "关羽"}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
        build_amap_config_js=lambda: b'window.AMAP_KEY="demo";window.AMAP_SECURITY="sec";',
        build_geovis_config_js=lambda: b'window.GEOVIS_TOKEN="geo";',
    )

    assert result["ok"] is True
    assert (tmp_path / "amap-config.js").read_text(encoding="utf-8") == 'window.AMAP_KEY="demo";window.AMAP_SECURITY="sec";'
    assert (tmp_path / "geovis-config.js").read_text(encoding="utf-8") == 'window.GEOVIS_TOKEN="geo";'


def test_generate_for_person_cache_hit_self_heals_missing_runtime_map_configs(tmp_path):
    md_path = tmp_path / "关羽.md"
    html_path = tmp_path / "关羽.html"
    md_path.write_text("# 关羽\n\n## 一、人物档案\n", encoding="utf-8")
    html_path.write_text(
        '<script>const data = {"person":{"name":"关羽"}};\nwindow.__EXPORT_DATA__ = data;</script>\n'
        '<script src="./amap-config.js"></script>\n'
        '<script src="./geovis-config.js"></script>',
        encoding="utf-8",
    )

    result = generation_service.generate_for_person(
        client=None,
        person="关羽",
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": "关羽"}},
        write_text=lambda path, content: Path(path).write_text(content, encoding="utf-8"),
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": "关羽"}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=type("Logger", (), {"warning": lambda *args, **kwargs: None})(),
        build_amap_config_js=lambda: b'window.AMAP_KEY="demo";window.AMAP_SECURITY="sec";',
        build_geovis_config_js=lambda: b'window.GEOVIS_TOKEN="geo";',
    )

    assert result["ok"] is True
    assert result["cached"] is True
    assert (tmp_path / "amap-config.js").read_text(encoding="utf-8") == 'window.AMAP_KEY="demo";window.AMAP_SECURITY="sec";'
    assert (tmp_path / "geovis-config.js").read_text(encoding="utf-8") == 'window.GEOVIS_TOKEN="geo";'


def test_generate_for_person_cache_hit_marks_degraded_when_runtime_config_write_fails(tmp_path):
    md_path = tmp_path / "关羽.md"
    html_path = tmp_path / "关羽.html"
    md_path.write_text("# 关羽\n\n## 一、人物档案\n", encoding="utf-8")
    html_path.write_text(
        '<script>const data = {"person":{"name":"关羽"}};\nwindow.__EXPORT_DATA__ = data;</script>\n'
        '<script src="/amap-config.js"></script>\n'
        '<script src="/geovis-config.js"></script>',
        encoding="utf-8",
    )

    warnings = []

    def _write_text(path, content):
        target = Path(path)
        if target.name in {"amap-config.js", "geovis-config.js"}:
            raise PermissionError(f"readonly: {target.name}")
        target.write_text(content, encoding="utf-8")

    logger = type("Logger", (), {"warning": lambda *args, **kwargs: warnings.append((args, kwargs))})()

    result = generation_service.generate_for_person(
        client=None,
        person="关羽",
        allow_cache=True,
        event_callback=None,
        story_paths=lambda _person: (str(md_path), str(html_path)),
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        extract_export_data_from_html=lambda _html: {"person": {"name": "关羽"}},
        write_text=_write_text,
        render_profile_html=lambda profile: f"<html>{profile['person']['name']}</html>",
        load_profile_from_md=lambda md, **_kwargs: {"person": {"name": "关羽"}, "locations": [], "markdown": md},
        normalize_markdown_tables=lambda md: md,
        compute_total_distance_km=lambda _md: None,
        insert_distance_intro=lambda md, _km: md,
        save_markdown=lambda _person, content: str(md_path),
        geocode_markdown_tool=lambda md: md,
        parse_story_markdown_tool=lambda _md: {"points": []},
        validate_story_markdown_tool=lambda _md: {"metrics": {}, "issues": []},
        render_html_fn=lambda title, points, md="": f"<html>{title}|{len(points)}|{md}</html>",
        render_amap_html=lambda title, points, info_html: f"<html>{title}|{len(points)}|{info_html}</html>",
        save_html=lambda _person, html: str(html_path),
        format_seconds=lambda sec: f"{sec:.2f}s",
        get_llm_client=lambda **_kwargs: object(),
        generate_historical_markdown=lambda _client, _person: "",
        cache_dependency_paths=[],
        logger=logger,
        build_amap_config_js=lambda: b'window.AMAP_KEY="demo";window.AMAP_SECURITY="sec";',
        build_geovis_config_js=lambda: b'window.GEOVIS_TOKEN="geo";',
    )

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["runtime_config_failed"] is True
    assert result["runtime_config_error"] == "readonly: amap-config.js"
    assert result["cached"] is True
    assert result["html_path"] == str(html_path)
    assert warnings
    assert not (tmp_path / "amap-config.js").exists()
    assert not (tmp_path / "geovis-config.js").exists()


def test_cli_target_resolution_does_not_fallback_to_question_sentence():
    targets = story_cli.resolve_targets_from_text(
        client=object(),
        text="苏轼为何总在南方活动？",
        extract_historical_figures=lambda _client, _text: [],
        fallback_to_input=True,
    )

    assert targets == []


def test_cli_target_resolution_can_fallback_to_plain_person_name():
    targets = story_cli.resolve_targets_from_text(
        client=object(),
        text="辛弃疾",
        extract_historical_figures=lambda _client, _text: [],
        fallback_to_input=True,
    )

    assert targets == ["辛弃疾"]


def test_story_agents_save_markdown_sanitizes_unsafe_name(tmp_path, monkeypatch):
    monkeypatch.setattr(story_agents, "_project_root", lambda: str(tmp_path))

    saved = story_agents.save_markdown("苏轼/黄州", "# 苏轼")

    assert Path(saved).name == "苏轼_黄州.md"
