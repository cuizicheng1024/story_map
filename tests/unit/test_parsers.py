
from storymap.script.core import parsers

def test_parse_story_document_collects_core_sections():
    md = """# 苏轼

## 一、人物档案

### 基本信息
- **姓名**：苏轼
- **时代**：北宋
- **出生**：1037年，眉州眉山（今四川省眉山市）
- **去世**：1101年，常州（今江苏省常州市）
- **享年**：64岁

### 生平概述
北宋文学家、书法家。

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：眉州眉山
- **公元纪年**：1037年
- **位置**：眉州眉山（今四川省眉山市）
- **事迹**：成长求学

### 📍 重要地点：黄州
- **公元纪年**：1080年
- **位置**：黄州（今湖北黄冈）
- **事迹**：谪居黄州
- **名句**：大江东去

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| 1037 | 眉州眉山 | 四川省眉山市 | 出生 |
| 1080 | 黄州 | 湖北黄冈 | 谪居黄州 |

## 地点坐标
| 现称 | 纬度 | 经度 |
| 四川省眉山市 | 30.048 | 103.831 |
| 湖北黄冈 | 30.45 | 114.87 |

## 人教版教材知识点
### 高中阶段
- 《念奴娇》

### 历史评价
- 旷达豪放
"""
    parsed = parsers.parse_story_document(md)

    assert parsed.basic_info.name == "苏轼"
    assert parsed.basic_info.dynasty == "北宋"
    assert parsed.overview == "北宋文学家、书法家。"
    assert len(parsed.timeline_rows) == 2
    assert len(parsed.location_sections) == 2
    assert parsed.coords_table["四川省眉山市"] == (30.048, 103.831)
    assert "《念奴娇》" in parsed.exam_points
    assert parsed.historical_reviews == ["旷达豪放"]

def test_normalize_markdown_tables_inserts_missing_separator():
    md = """## 四、生平时间线
| 年份 | 现称 | 事件 |
| 1037 | 四川省眉山市 | 出生 |
"""

    normalized = parsers._normalize_markdown_tables(md)
    lines = normalized.splitlines()

    assert lines[1] == "| 年份 | 现称 | 事件 |"
    assert lines[2] == "| --- | --- | --- |"

def test_parse_story_document_prefers_timeline_table_over_coords_table():
    md = """# 人物甲

## 四、生平时间线

| 年份 | 阶段 | 关键事件 |
| --- | --- | --- |
| 1900 | 出生 | 生于甲地 |

## 五、地点坐标

| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 甲地 | 甲市 | 30.000000 | 120.000000 |
"""

    parsed = parsers.parse_story_document(md)

    assert parsed.timeline_header == ["年份", "阶段", "关键事件"]
    assert parsed.timeline_rows == [["1900", "出生", "生于甲地"]]

def test_pick_geocode_name_collapses_foreign_admin_chain_to_city_leaf():
    assert parsers._pick_geocode_name("美国纽约州纽约市") == "纽约市"
    assert parsers._pick_geocode_name("纽约州纽约市") == "纽约市"
    assert parsers._pick_geocode_name("韩国庆尚北道庆州市") == "庆州市"

def test_pick_geocode_name_keeps_plain_city_name():
    assert parsers._pick_geocode_name("纽约市") == "纽约市"
    assert parsers._pick_geocode_name("巴黎") == "巴黎"

def test_parse_date_location_details_treats_alive_marker_as_no_death():
    date, loc, geocode_loc = parsers._parse_date_location_details("健在（截至2024年7月）", ["卒于", "去世于", "卒"])

    assert date == ""
    assert loc == ""
    assert geocode_loc == ""

def test_parse_date_location_details_strips_parenthetical_native_place_from_birthplace():
    date, loc, geocode_loc = parsers._parse_date_location_details(
        "1957年9月，北京（祖籍河北赵县）",
        ["出生于", "生于"],
    )

    assert date == "1957年"
    assert loc == "北京"
    assert geocode_loc == "北京"

def test_extract_native_place_from_story_text_can_fallback_to_overview():
    md = """# 王安石

## 人物档案

### 基本信息
- **姓名**：王安石
- **出生**：约公元1021年，古称临江军清江县（今江西省樟树市）

### 生平概述
王安石，字介甫，号半山，祖籍抚州临川，出生于临江军清江县（今江西省樟树市）。
"""

    assert parsers._extract_native_place_from_story_text(md) == "抚州临川"

def test_parse_date_location_details_drops_birthplace_when_birth_field_only_declares_native_place():
    date, loc, geocode_loc = parsers._parse_date_location_details(
        "约公元前140年，籍贯杜陵（今陕西省西安市）",
        ["出生于", "生于"],
    )

    assert date == "约公元前140年"
    assert loc == ""
    assert geocode_loc == ""
