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
