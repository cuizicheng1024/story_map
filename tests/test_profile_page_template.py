import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import map_html_renderer as renderer
from map_html_renderer import render_profile_html
from artifacts import _extract_export_data_from_html
import profile_builder
import story_map


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
    assert "personName: String(data?.person?.name || '').trim()" in html


def test_render_profile_html_includes_google_analytics_snippet():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "googletagmanager.com/gtag/js?id=G-74J5L22QGX" in html
    assert "gtag('config', \"G-74J5L22QGX\")" in html


def test_build_info_panel_html_initializes_wrapper():
    html = renderer.build_info_panel_html("测试人物", {"朝代": "西汉", "身份": "外交使者"})

    assert 'class="bio-panel"' in html
    assert "西汉" in html
    assert "外交使者" in html


def test_render_profile_html_falls_back_to_raw_knowledge_graph(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    renderer._build_stellar_home_fallback.cache_clear()
    monkeypatch.setattr(renderer, "STELLAR_HOME_DATA_JSON", REPO_ROOT / "artifacts" / "story_map" / "__missing_home_data__.json")

    html = render_profile_html(
        {
            "person": {"name": "张骞", "dynasty": "西汉"},
            "locations": [],
            "highlights": {},
            "markdown": "# 张骞\n\n张骞出使西域，与汉武帝关系密切。",
        }
    )

    payload = _extract_export_data_from_html(html)
    related = payload.get("relatedGraph") or {}

    assert len(related.get("nodes") or []) >= 1
    assert any(str(node.get("name") or "") == "汉武帝" for node in (related.get("nodes") or []))


def test_load_profile_prefers_work_quote_for_literary_person():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李斯.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "泰山不让土壤" in str(profile["person"].get("quote") or "")
    assert "泰山不让土壤" in str(profile["person"].get("shortReview") or "")


def test_load_profile_prefers_literary_persons_own_work_for_short_review():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李白.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "犬吠水声中" in str(profile["person"].get("shortReview") or "")


def test_load_profile_prefers_external_literary_review_for_non_literary_person():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "王昭君.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert str(profile["person"].get("shortReview") or "") == "画图省识春风面，环佩空归月夜魂。"


def test_choose_short_review_prefers_personal_sharp_remark_for_non_literary_fallback():
    review = profile_builder.choose_short_review(
        info={"主要身份": "政治家、将领"},
        locations=[{"quotes": "《奏疏》：“先天下之忧而忧。”；临终慨叹：“大势已去，奈何！”"}],
        work_texts={"奏疏": "先天下之忧而忧。"},
        historical_reviews=[],
        fallback="",
    )

    assert review == "大势已去，奈何！"


def test_load_profile_extracts_work_texts_for_teaching_links():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "柳永.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)
    work_texts = profile.get("workTexts") or {}

    assert "望海潮·东南形胜" in work_texts
    assert "东南形胜" in str(work_texts["望海潮·东南形胜"])
    assert work_texts.get("望海潮") == work_texts.get("望海潮·东南形胜")


def test_load_profile_extracts_context_fallback_for_work_without_direct_quote():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "诸葛亮.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)
    work_texts = profile.get("workTexts") or {}

    assert "隆中对" in work_texts
    assert "三分天下" in str(work_texts["隆中对"])


def test_render_profile_html_hides_tool_layer_section():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "本次使用工具" not in html


def test_render_profile_html_limits_teaching_review_subtitle_to_short_lines():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const extractTeachingReviewSubtitle = (raw) => {" in html
    assert "const splitRe = new RegExp(`${CR}${LF}|${CR}|${LF}|${BS}${BS}n`, 'g');" in html
    assert "if (t.length > 80) return true;" in html


def test_render_profile_html_prefers_short_review_and_work_hover_helpers():
    html = render_profile_html({"person": {"name": "测试人物", "shortReview": "短评"}, "locations": [], "highlights": {}})

    assert "const shortReview = String(data.person?.shortReview || data.person?.quote || '').trim();" in html
    assert "const renderWorkTitleWithTooltip = (fullTitle, key, className) => {" in html
