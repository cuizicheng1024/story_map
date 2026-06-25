import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.profile import builder as profile_builder
from storymap.script.profile import renderer as map_html_renderer
from storymap.script.core import parsers as parser_utils


def test_profile_map_bootstrap_uses_official_geovis_terrain_metadata_url():
    html = map_html_renderer._profile_map_bootstrap_html()

    assert "/base/v1/terrain/layer.json?token=" in html


def test_profile_map_bootstrap_exposes_geovis_terrain_runtime_helpers():
    html = map_html_renderer._profile_map_bootstrap_html()

    assert "terrainServiceUrl: _geoVisTerrainServiceUrl" in html
    assert "terrainRootUrl: _geoVisTerrainRootUrl" in html


def test_profile_map_bootstrap_uses_runtime_geovis_config_without_inlining_token():
    html = map_html_renderer._profile_map_bootstrap_html()

    assert "geovis-config.js" in html
    assert "window.GEOVIS_TOKEN=" not in html
    assert "window.MAP_STORY_STATIC_SITE !== true || isDevHost" in html


def test_amap_bootstrap_allows_localhost_runtime_config_even_in_static_mode():
    html = map_html_renderer._amap_bootstrap_html()

    assert "amap-config.js" in html
    assert "window.MAP_STORY_STATIC_SITE !== true || isDevHost" in html


def test_extract_work_texts_prefers_textbook_quote_for_zhongguo_shigongqiao():
    md_path = REPO_ROOT / "storymap" / "examples" / "story" / "李春.md"
    md = md_path.read_text(encoding="utf-8")

    work_texts = profile_builder.extract_work_texts(md)

    assert "中国石拱桥" in work_texts
    assert "桥的设计完全合乎科学原理" in work_texts["中国石拱桥"]
    assert "李春本人无文学作品传世" not in work_texts["中国石拱桥"]


def test_extract_work_texts_uses_derived_quote_for_ji_chengtian_si_ye_you_when_missing():
    work_texts = profile_builder.extract_work_texts("相关作品：苏轼著有《记承天寺夜游》。")

    assert "记承天寺夜游" in work_texts
    assert "庭下如积水空明" in work_texts["记承天寺夜游"]


def test_extract_work_texts_for_liuhui_excludes_jiuzhang_suanshu_source_text():
    md_path = REPO_ROOT / "storymap" / "examples" / "story" / "刘徽.md"
    md = md_path.read_text(encoding="utf-8")

    work_texts = profile_builder.extract_work_texts(md)

    assert "九章算术注" in work_texts
    assert "海岛算经" in work_texts
    assert "九章算术" not in work_texts


def test_split_quote_lines_keeps_semicolon_inside_single_quote():
    parts = profile_builder.split_quote_lines("《谏逐客书》：“是以泰山不让土壤，故能成其大；河海不择细流，故能就其深。”；临刑前感叹：“吾欲与若复牵黄犬俱出上蔡东门逐狡兔，岂可得乎！”")

    assert parts == [
        "《谏逐客书》：“是以泰山不让土壤，故能成其大；河海不择细流，故能就其深。”",
        "临刑前感叹：“吾欲与若复牵黄犬俱出上蔡东门逐狡兔，岂可得乎！”",
    ]


def test_sparse_single_site_locations_collapse_speculative_expansion():
    loc_items = [
        {
            "name": "赵州桥选址地",
            "ancientName": "赵州洨河",
            "modernName": "河北省石家庄市赵县洨河",
            "lat": 37.7556,
            "lng": 114.7633,
            "type": "normal",
            "event": "勘察洨河水文地质，选定桥址。",
            "time": "约公元605年前后",
            "duration": "",
            "significance": "科学的选址是赵州桥稳固的关键。",
            "works": [],
            "quoteLines": [],
        },
        {
            "name": "赵州桥建造工地",
            "ancientName": "赵州城南洨河",
            "modernName": "河北省石家庄市赵县洨河之上",
            "lat": 37.7556,
            "lng": 114.7633,
            "type": "normal",
            "event": "主持设计、施工，采用敞肩拱结构。",
            "time": "约公元605-618年",
            "duration": "十余年",
            "significance": "完成世界桥梁史上的不朽杰作。",
            "works": ["中国石拱桥"],
            "quoteLines": [],
        },
        {
            "name": "石料采集场（推断）",
            "ancientName": "古称不详",
            "modernName": "河北省赞皇县太行山区",
            "lat": 37.6611,
            "lng": 114.3833,
            "type": "normal",
            "event": "组织石料开采（推断）。",
            "time": "约公元605-610年",
            "duration": "数年",
            "significance": "推断地点。",
            "works": [],
            "quoteLines": [],
        },
    ]

    collapsed = profile_builder._collapse_sparse_single_site_locations(loc_items)

    assert len(collapsed) == 1
    assert collapsed[0]["modernName"] == "河北省石家庄市赵县洨河之上"
    assert "选定桥址" in collapsed[0]["event"]
    assert "主持设计、施工" in collapsed[0]["event"]
    assert collapsed[0]["works"] == ["中国石拱桥"]


def test_sparse_single_site_locations_collapse_merges_unique_quotes():
    loc_items = [
        {
            "name": "承天寺",
            "ancientName": "承天寺",
            "modernName": "湖北黄冈承天寺",
            "lat": 30.4530,
            "lng": 114.8723,
            "type": "normal",
            "event": "夜游承天寺。",
            "time": "元丰六年",
            "duration": "",
            "significance": "寄托闲情。",
            "works": ["记承天寺夜游"],
            "quoteLines": ["庭下如积水空明，水中藻、荇交横，盖竹柏影也。"],
        },
        {
            "name": "承天寺旧址",
            "ancientName": "承天寺",
            "modernName": "湖北黄冈承天寺旧址",
            "lat": 30.4530,
            "lng": 114.8723,
            "type": "normal",
            "event": "与张怀民同游。",
            "time": "元丰六年",
            "duration": "",
            "significance": "见月色如水。",
            "works": ["记承天寺夜游"],
            "quoteLines": ["但少闲人如吾两人者耳。"],
        },
    ]

    collapsed = profile_builder._collapse_sparse_single_site_locations(loc_items)

    assert len(collapsed) == 1
    assert collapsed[0]["works"] == ["记承天寺夜游"]
    assert collapsed[0]["quoteLines"] == [
        "庭下如积水空明，水中藻、荇交横，盖竹柏影也。",
        "但少闲人如吾两人者耳。",
    ]


def test_sparse_single_site_locations_does_not_collapse_distinct_precise_places_with_yidai_suffix():
    loc_items = [
        {
            "name": "河东解县",
            "ancientName": "河东郡解县",
            "modernName": "山西省运城市盐湖区解州镇一带",
            "lat": 35.0274,
            "lng": 111.0012,
            "type": "birth",
            "event": "早年成长于此。",
            "time": "约160年",
            "duration": "",
            "significance": "关羽的籍贯与文化根脉所在。",
            "works": [],
            "quoteLines": [],
        },
        {
            "name": "涿郡",
            "ancientName": "涿郡涿县",
            "modernName": "河北省保定市涿州市一带",
            "lat": 39.4858,
            "lng": 115.9734,
            "type": "normal",
            "event": "与刘备起兵于此。",
            "time": "184年",
            "duration": "",
            "significance": "政治与军事生涯的起点。",
            "works": [],
            "quoteLines": [],
        },
    ]

    collapsed = profile_builder._collapse_sparse_single_site_locations(loc_items)

    assert len(collapsed) == 2
    assert [item["name"] for item in collapsed] == ["河东解县", "涿郡"]


def test_build_profile_data_marks_coordinates_as_wgs84():
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋
- **出生**：1037年，眉州眉山（今四川省眉山市）
- **去世**：1101年，常州（今江苏省常州市）

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：开封
- **公元纪年**：1057年
- **位置**：汴京（今河南省开封市）
- **事迹**：赴京应试。

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 四川省眉山市 | 30.0480 | 103.8310 |
| 河南省开封市 | 34.7970 | 114.3070 |
| 江苏省常州市 | 31.8100 | 119.9740 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text.replace("（今", "").replace("）", "")),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["coordinateSystem"] == "WGS84"
    assert profile["person"]["birth"]["coordSystem"] == "WGS84"
    assert profile["person"]["death"]["coordSystem"] == "WGS84"
    assert all(item.get("coordSystem") == "WGS84" for item in profile["locations"])


def test_parse_date_location_details_preserves_uncertain_year_marker():
    date, loc, geocode_loc = parser_utils._parse_date_location_details(
        "约公元619年（存疑），婺州义乌（今浙江义乌）",
        ["出生于", "生于"],
    )

    assert date == "约公元619年（存疑）"
    assert "婺州义乌" in loc
    assert geocode_loc == loc


def test_parse_date_location_details_keeps_ambiguous_death_outcome_as_raw_location():
    date, loc, geocode_loc = parser_utils._parse_date_location_details(
        "约公元684年，结局存疑（一说被杀于扬州，一说逃遁不知所终）",
        ["卒于", "去世于", "卒"],
    )

    assert date == "约公元684年（存疑）"
    assert loc == "结局存疑（一说被杀于扬州，一说逃遁不知所终）"
    assert geocode_loc == ""


def test_build_profile_data_keeps_clear_birthplace_but_strips_date_only_uncertainty():
    md = """# 柳永

## 一、人物档案

### 基本信息
- **姓名**：柳永
- **时代**：北宋
- **出生**：约984年，崇安（今福建省南平市武夷山市）（存疑，一说生于987年）

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 福建省南平市武夷山市 | 27.7560 | 118.0320 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("崇安", "福建省南平市武夷山市") if "武夷山" in text else ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["birthplace"] == "崇安（今福建省南平市武夷山市）"
    assert profile["person"]["birth"]["location"] == "崇安（今福建省南平市武夷山市）"
    assert profile["person"]["birth"]["lat"] == 27.756
    assert profile["person"]["birth"]["lng"] == 118.032


def test_build_profile_data_keeps_ambiguous_birthplace_text_but_drops_birth_coord():
    md = """# 柏拉图

## 一、人物档案

### 基本信息
- **姓名**：柏拉图
- **时代**：古希腊古典时代
- **出生**：约公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 希腊雅典 | 37.9838 | 23.7275 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("雅典", "希腊雅典") if "雅典" in text else ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["birthplace"] == "雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）"
    assert profile["person"]["birth"]["location"] == "雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）"
    assert profile["person"]["birth"]["lat"] is None
    assert profile["person"]["birth"]["lng"] is None


def test_build_profile_data_drops_birth_coord_for_parenthetical_alternate_birthplace_note():
    md = """# 柏拉图

## 一、人物档案

### 基本信息
- **姓名**：柏拉图
- **时代**：古希腊古典时代
- **出生**：约公元前427年，出生于雅典（存疑：另有传说出自科林斯地峡附近的埃癸那岛）

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 希腊雅典 | 37.9838 | 23.7275 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("雅典", "希腊雅典") if "雅典" in text else ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["birthplace"] == "雅典（存疑：另有传说出自科林斯地峡附近的埃癸那岛）"
    assert profile["person"]["birth"]["location"] == "雅典（存疑：另有传说出自科林斯地峡附近的埃癸那岛）"
    assert profile["person"]["birth"]["lat"] is None
    assert profile["person"]["birth"]["lng"] is None


def test_build_profile_data_does_not_use_historical_lookup_for_ambiguous_birthplace():
    md = """# 柏拉图

## 一、人物档案

### 基本信息
- **姓名**：柏拉图
- **时代**：古希腊古典时代
- **出生**：约公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("雅典", "希腊雅典") if "雅典" in text else ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: (37.9838, 23.7275),
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["birth"]["lat"] is None
    assert profile["person"]["birth"]["lng"] is None


def test_build_profile_data_includes_work_summaries_from_index(monkeypatch):
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋
- **出生**：1037年，眉州眉山（今四川省眉山市）

### 生平概述
测试人物创作《赤壁赋》。
"""

    monkeypatch.setattr(
        profile_builder,
        "_get_work_summary_item",
        lambda title: {
            "title": "赤壁赋",
            "authors": ["苏轼"],
            "one_liner": "借赤壁夜游抒发人生感慨。",
            "genre": "赋",
        }
        if str(title or "").strip() == "赤壁赋"
        else {},
    )

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text.replace("（今", "").replace("）", "")),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["workSummaries"]["赤壁赋"]["authors"] == ["苏轼"]
    assert profile["workSummaries"]["赤壁赋"]["genre"] == "赋"


def test_build_profile_data_includes_person_aliases_from_bio_fields():
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋
- **字**：子瞻
- **号**：东坡居士
- **别名**：测试君、试验者
- **出生**：1037年，眉州眉山（今四川省眉山市）
- **去世**：1101年，常州（今江苏省常州市）
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text.replace("（今", "").replace("）", "")),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["courtesyName"] == "子瞻"
    assert profile["person"]["artName"] == "东坡居士"
    assert profile["person"]["aliases"] == ["测试君", "试验者", "子瞻", "东坡居士"]


def test_build_profile_data_prefers_summary_index_copy(monkeypatch):
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋
- **主要身份**：文学家
- **历史地位**：被誉为“旧称号”
- **主要成就**：旧成就

### 历史评价
- 人物短评：旧短评。
"""

    monkeypatch.setattr(
        profile_builder,
        "_get_person_summary_item",
        lambda name: {
            "title": "新称号",
            "short_review": "新短评",
            "status": "新的历史地位",
            "identities": "政治家、文学家",
            "achievements": "新的主要成就",
            "works": ["赤壁赋"],
            "reviews": ["新的历史评价"],
        }
        if name == "测试人物"
        else {},
    )

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["title"] == "新称号"
    assert profile["person"]["shortReview"] == "新短评"
    assert profile["person"]["quote"] == "新短评"
    assert profile["person"]["highlights"]["honor"] == "新称号"
    assert profile["person"]["highlights"]["status"] == "新的历史地位"
    assert profile["person"]["highlights"]["identities"] == "政治家、文学家"
    assert profile["person"]["highlights"]["achievements"] == "新的主要成就"
    assert profile["person"]["highlights"]["works"] == ["赤壁赋"]
    assert profile["person"]["highlights"]["reviews"][0] == "新的历史评价"


def test_build_profile_data_filters_summary_works_and_backfills_preferred_titles(monkeypatch):
    md = """# 列宁

## 一、人物档案

### 基本信息
- **姓名**：弗拉基米尔·伊里奇·乌里扬诺夫（列宁）
- **时代**：19世纪末至20世纪初
"""

    monkeypatch.setattr(
        profile_builder,
        "_get_person_summary_item",
        lambda name: {
            "works": ["火星报"],
        }
        if name == "弗拉基米尔·伊里奇·乌里扬诺夫"
        else {},
    )

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["highlights"]["works"] == [
        "帝国主义是资本主义的最高阶段",
        "国家与革命",
    ]


def test_build_profile_data_normalizes_summary_achievements_for_known_people(monkeypatch):
    md = """# 方志敏

## 一、人物档案

### 基本信息
- **姓名**：方志敏
- **时代**：近现代
"""

    monkeypatch.setattr(
        profile_builder,
        "_get_person_summary_item",
        lambda name: {
            "achievements": "创建赣东北革命根据地；创立中国工农红军第十军团；坚持斗争。",
        }
        if name == "方志敏"
        else {},
    )

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["highlights"]["achievements"] == (
        "创建赣东北革命根据地；创建中国工农红军第十军，并在红十军团成立后担任重要领导职务；坚持斗争。"
    )


def test_build_profile_data_uses_fallback_person_when_markdown_lacks_name():
    md = """## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 湖北黄冈 | 30.45 | 114.87 |
"""

    profile = profile_builder.build_profile_data(
        md,
        fallback_person="李四光",
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["name"] == "李四光"
    assert profile["locations"][0]["modernName"] == "湖北黄冈"


def test_build_profile_data_preserves_parenthetical_display_name():
    md = """# 鲁迅

## 人物档案

### 基本信息
- **姓名**：鲁迅（周树人）
- **历史地位**：中国现代文学的奠基人
"""

    profile = profile_builder.build_profile_data(
        md,
        fallback_person="鲁迅",
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["person"]["name"] == "鲁迅（周树人）"


def test_build_profile_data_keeps_single_birth_location_when_only_birth_coord_exists():
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **出生**：1037年，眉州眉山（今四川省眉山市）

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 四川省眉山市 | 30.0480 | 103.8310 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text.replace("（今", "").replace("）", "")),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert len(profile["locations"]) == 1
    assert profile["locations"][0]["type"] == "birth"
    assert "四川省眉山市" in str(profile["locations"][0]["modernName"] or "")


def test_sort_profile_locations_keeps_unknown_birth_before_dated_death():
    loc_items = [
        {
            "name": "巴西郡（阆中）",
            "type": "normal",
            "time": "214年-221年",
            "event": "长期镇守此地。",
            "significance": "",
        },
        {
            "name": "阆中",
            "type": "death",
            "time": "221年",
            "event": "遇害。",
            "significance": "",
        },
        {
            "name": "涿郡",
            "type": "birth",
            "time": "生年不详",
            "event": "出生。",
            "significance": "",
        },
    ]

    ordered = profile_builder._sort_profile_locations(loc_items)

    assert [item["type"] for item in ordered] == ["birth", "normal", "death"]
    assert [item["name"] for item in ordered] == ["涿郡", "巴西郡（阆中）", "阆中"]


def test_sort_profile_locations_does_not_treat_century_text_as_year_12():
    loc_items = [
        {
            "name": "克烈部王汗驻地",
            "type": "normal",
            "time": "约12世纪80年代",
            "event": "早期依附王汗。",
            "significance": "",
        },
        {
            "name": "漠北斡难河上游",
            "type": "birth",
            "time": "约1162年",
            "event": "出生。",
            "significance": "",
        },
        {
            "name": "斡难河源",
            "type": "normal",
            "time": "1206年",
            "event": "建国。",
            "significance": "",
        },
    ]

    ordered = profile_builder._sort_profile_locations(loc_items)

    assert [item["name"] for item in ordered] == ["漠北斡难河上游", "斡难河源", "克烈部王汗驻地"]


def test_sort_profile_locations_does_not_push_undated_normal_past_death():
    """复现马可·波罗页面的"最后行迹被显示成杭州"bug：

    Markdown 中"杭州（行在）"的时间是"在华期间（具体时间不详）"，无法被
    `_extract_location_time_bounds` 解析出数字年份。修复前会被甩到末尾，越过
    1324 年的去世节点；修复后应在邻近年份间插值，保持原顺序的合理位置。
    """

    loc_items = [
        {"name": "威尼斯（出生）", "type": "birth", "time": "约1254年", "event": "出生"},
        {"name": "威尼斯（出发）", "type": "normal", "time": "约1271年", "event": ""},
        {"name": "撒马尔罕", "type": "normal", "time": "约1273年（途径）", "event": ""},
        {"name": "元上都", "type": "normal", "time": "约1275年夏", "event": ""},
        {"name": "元大都", "type": "normal", "time": "约1275年 - 约1292年（主要居住）", "event": ""},
        {"name": "杭州（行在）", "type": "normal", "time": "在华期间（具体时间不详）", "event": "出使巡查"},
        {"name": "泉州（刺桐）", "type": "normal", "time": "约1292年", "event": ""},
        {"name": "威尼斯（归国）", "type": "normal", "time": "约1295年", "event": ""},
        {"name": "威尼斯（去世）", "type": "death", "time": "公元1324年", "event": "去世"},
    ]

    ordered = profile_builder._sort_profile_locations(loc_items)
    names = [item["name"] for item in ordered]
    # 第一个必须是出生，最后一个必须是去世
    assert names[0] == "威尼斯（出生）"
    assert names[-1] == "威尼斯（去世）"
    # 杭州不应被排到所有有年份行迹之后
    assert names.index("杭州（行在）") < names.index("泉州（刺桐）")
    assert names.index("杭州（行在）") < names.index("威尼斯（归国）")
    assert names.index("杭州（行在）") < names.index("威尼斯（去世）")


def test_build_profile_data_uses_coords_table_as_last_resort_when_info_exists_but_no_locations():
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 湖北黄冈 | 30.45 | 114.87 |
| 北京 | 39.90 | 116.40 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("", text),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert [item["modernName"] for item in profile["locations"]] == ["湖北黄冈", "北京"]
    assert all(item["type"] == "move" for item in profile["locations"])


def test_death_location_heuristic_ignores_generic_endpoint_language():
    item = {
        "type": "normal",
        "event": "抵达阶段终点，准备转入下一段人生。",
        "significance": "这只是行程节点，不代表去世。",
    }

    assert profile_builder._looks_like_death_location(item) is False


def test_death_location_heuristic_keeps_explicit_death_event():
    item = {
        "type": "normal",
        "event": "晚年病逝。",
        "significance": "生命终章。",
    }

    assert profile_builder._looks_like_death_location(item) is True


def test_extract_title_from_text_prefers_honorific_title_over_generic_quote():
    text = "中国历史上以“忠义”著称的名将，被后世尊为“武圣”。"

    assert profile_builder.extract_title_from_text(text) == "武圣"


def test_extract_title_from_text_ignores_regnal_era_phrase():
    text = "中国历史上唯一正统的女皇帝，其统治上承“贞观之治”，下启“开元盛世”。"

    assert profile_builder.extract_title_from_text(text) == ""


def test_build_profile_data_infers_location_significance_when_missing():
    md = """# 关羽

## 一、人物档案

### 基本信息
- **姓名**：关羽
- **时代**：东汉末年

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：许都
- **公元纪年**：200年
- **位置**：许都（今河南许昌）
- **事迹**：挂印封金，重归刘备

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 河南许昌 | 34.0311 | 113.8520 |
"""

    profile = profile_builder.build_profile_data(
        md,
        allow_geocode=False,
        event_callback=None,
        split_ancient_modern=lambda text, _cb: ("许都", "河南许昌"),
        batch_split_ancient_modern=lambda _items, event_callback=None: None,
        fuzzy_coord_lookup=profile_builder._loose_coord_lookup,
        lookup_coords_from_historical_index=lambda *args: None,
        resolve_place_coord=lambda *args: None,
        build_points_fn=lambda *args, **kwargs: [],
    )

    assert profile is not None
    assert profile["locations"]
    assert profile["locations"][0]["significance"]
    assert "关羽" in profile["locations"][0]["significance"]
