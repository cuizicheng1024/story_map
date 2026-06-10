import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import map_client
import generation_service
import story_agents
import story_cli
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

    result = sm.generate_for_person(client=None, person=person, allow_cache=True)

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["refreshed"] is True
    assert "NEW_MARKDOWN" in html_path.read_text(encoding="utf-8")
    assert "OLD" not in html_path.read_text(encoding="utf-8")


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
    assert result["_agent_runtime"]["llm_calls_used"] == 2
    assert result["_agent_runtime"]["execution_trace"] == ["supervisor", "search_agent", "editor_agent", "critic_agent"]
    assert result["_agent_runtime"]["tool_traces"] == [{"tool_name": "search_person_info"}]
    assert result["_agent_runtime"]["memory_hits"] == {"search": 1}
    assert result["_agent_runtime"]["memory_misses"] == {"place_map": 1}
    assert result["_state"]["agent_runtime"]["llm_calls_limit"] == 4
    assert result["_state"]["agent_runtime"]["tool_specs"] == [{"name": "search_person_info"}]
    assert refreshed == [person]
    assert md_path.exists()
    assert out_html.exists()
    assert "地点坐标" in md_path.read_text(encoding="utf-8")
    assert person in out_html.read_text(encoding="utf-8")
    assert "黄冈" in out_html.read_text(encoding="utf-8")


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
        + "| 现称 | 现代搜索地名 | 纬度 | 经度 |\n"
        + "| --- | --- | --- | --- |\n"
        + "| 黄冈 | 湖北黄冈 | 30.45 | 114.87 |\n"
        + "| 北京 | 北京 | 39.90 | 116.40 |\n",
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

    result = sm.generate_for_person(client=object(), person=person, allow_cache=False)

    assert result["ok"] is True
    saved_md = md_path.read_text(encoding="utf-8")
    assert "总行程估算" in saved_md
    assert "地点坐标（自动地理编码）" in saved_md


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
| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 出生于眉州眉山 | 出生于眉州眉山 | 39.913704 | 116.362106 |
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
| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 四川省眉山市东坡区 | 四川省眉山市东坡区 | 39.913704 | 116.362106 |
"""

    monkeypatch.setattr(map_client, "geocode_city", lambda name: (30.0483, 103.8318) if "眉山" in name else None)

    result = map_client.append_coords_section(md)

    assert result.count("## 地点坐标（自动地理编码）") == 1
    assert "30.048300 | 103.831800" in result
    assert "39.913704" not in result


def test_compute_total_distance_km_supports_auto_generated_coords_table():
    md = """## 地点坐标（自动地理编码）
| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 黄州 | 湖北黄冈 | 30.45 | 114.87 |
| 惠州 | 广东惠州 | 23.08 | 114.41 |
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
