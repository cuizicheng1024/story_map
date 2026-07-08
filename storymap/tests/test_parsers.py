"""锁住 parsers 核心解析行为。

跑: ``python3 -m pytest storymap/tests/test_parsers.py -v``
"""
from __future__ import annotations

from storymap.script.core.parsers import (
    BANNED_PLACE_KEYS,
    extract_inline_coord_pair,
    extract_native_place_from_story_text,
    normalize_markdown_tables,
    normalize_place_key,
    parse_basic_info,
    parse_date_location,
    parse_date_location_details,
    pick_geocode_name,
)


class TestNormalizePlaceKey:
    def test_strips_county_suffixes(self):
        # 郡 在 suffix 列表中会被去除
        assert normalize_place_key("洛阳郡") == "洛阳"

    def test_handles_empty(self):
        assert normalize_place_key("") == ""
        assert normalize_place_key("  ") == ""

    def test_strips_jin_prefix(self):
        assert normalize_place_key("今长安") == "长安"

    def test_banned_keys(self):
        for key in BANNED_PLACE_KEYS:
            result = normalize_place_key(key)
            assert isinstance(result, str)


class TestNormalizeMarkdownTables:
    def test_normalizes_pipe_spacing(self):
        raw = "| 姓名 | 朝代 |\n| --- | --- |\n| 李白 | 唐 |"
        result = normalize_markdown_tables(raw)
        assert "李白" in result

    def test_handles_empty(self):
        assert isinstance(normalize_markdown_tables(""), str)
        assert isinstance(normalize_markdown_tables("   "), str)


class TestParseBasicInfo:
    def test_parses_simple_fields(self):
        md = "# 李白\n\n## 人物档案\n### 基本信息\n- **姓名**：李白\n- **字号**：太白\n"
        info = parse_basic_info(md)
        assert isinstance(info, dict)
        assert info.get("姓名") == "李白"
        assert info.get("字号") == "太白"

    def test_handles_empty(self):
        assert parse_basic_info("") == {}
        assert parse_basic_info("   ") == {}


class TestParseDateLocation:
    def test_handles_basic(self):
        date_text, loc = parse_date_location("生于公元701年，出生于碎叶城", ["出生于", "生于"])
        assert date_text == "公元701年"
        assert "碎叶" in loc

    def test_handles_empty(self):
        date_text, loc = parse_date_location("", ["出生于"])
        assert date_text == ""
        assert loc == ""


class TestParseDateLocationDetails:
    def test_extracts_birth_prefix(self):
        date_text, loc, geocode_loc = parse_date_location_details(
            "出生于公元701年碎叶城", ["出生于", "生于"]
        )
        assert date_text == "公元701年"
        assert "碎叶" in loc

    def test_extracts_death_prefix(self):
        date_text, loc, geocode_loc = parse_date_location_details(
            "卒于公元762年当涂县", ["卒于", "去世于", "卒"]
        )
        assert date_text == "公元762年"
        assert "当涂" in loc

    def test_handles_empty(self):
        date_text, loc, geocode_loc = parse_date_location_details("", ["出生于"])
        assert date_text == ""
        assert loc == ""


class TestExtractNativePlace:
    def test_extracts_jiguan(self):
        result = extract_native_place_from_story_text(
            "籍贯：四川青莲乡", basic_info_map={}, overview=""
        )
        assert result is not None
        assert isinstance(result, str)


class TestPickGeocodeName:
    def test_picks_simpler_name(self):
        result = pick_geocode_name("长安（今西安）")
        assert result in ("西安", "长安")

    def test_handles_empty(self):
        assert pick_geocode_name("") == ""

    def test_long_text_still_returns(self):
        result = pick_geocode_name("非常长的地名超过二十个字的地方")
        assert isinstance(result, str)


class TestExtractInlineCoordPair:
    def test_handles_empty(self):
        assert extract_inline_coord_pair("") is None
        assert extract_inline_coord_pair("普通文本") is None

    def test_finds_coords(self):
        result = extract_inline_coord_pair("坐标：39.9, 116.4")
        assert result is not None
        lat, lng = result
        assert abs(lat - 39.9) < 0.01
        assert abs(lng - 116.4) < 0.01
