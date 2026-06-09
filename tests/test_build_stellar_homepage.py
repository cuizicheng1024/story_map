import importlib


def test_render_index_html_emits_valid_regex_literals():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert r'replace(/^\\/+/, "")' not in html
    assert r'replace(/\\/+$/, "")' not in html
    assert r'replace(/^今\\s*/g, "")' not in html
    assert r'replace(/^约\\s*/g, "")' not in html
    assert r'replace(/^公元前?\\d+年\\s*/g, "")' not in html
    assert r'replace(/^\/+/, "")' in html
    assert r'replace(/\/+$/, "")' in html
    assert r'replace(/^今\s*/g, "")' in html
    assert r'replace(/^约\s*/g, "")' in html
    assert r'replace(/^公元前?\d+年\s*/g, "")' in html
    assert r'window.__openPerson(\'' not in html
    assert 'window.__openPerson(\'" + personJs + "\')' in html


def test_resolve_main_role_band_prefers_primary_identity_field():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="**主要身份**：政治家、军事家、谋略家\n",
        domain_tags=[],
        review="",
        quote="",
    )

    assert band == "politics"
    assert label == "政治家"


def test_resolve_main_role_band_can_fallback_to_domain_tags():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="",
        domain_tags=["诗人", "书法家"],
        review="",
        quote="",
    )

    assert band == "literature"
    assert label == "诗人"


def test_resolve_main_role_band_places_philosophers_into_academic_band():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="**主要身份**：哲学家、教育家、思想家\n",
        domain_tags=[],
        review="",
        quote="",
    )

    assert band == "academic"
    assert label == "哲学家"
