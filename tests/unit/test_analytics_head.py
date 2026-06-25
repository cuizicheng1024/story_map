from __future__ import annotations

from storymap.script.core.analytics import analytics_head_html


def test_analytics_head_html_returns_empty_without_explicit_config(monkeypatch):
    monkeypatch.delenv("MAP_STORY_GA_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("MAP_STORY_VOLCENGINE_APM_TOKEN", raising=False)
    monkeypatch.delenv("VOLCENGINE_APM_TOKEN", raising=False)

    assert analytics_head_html(page_type="homepage", page_name="首页") == ""


def test_analytics_head_html_includes_google_analytics_when_configured(monkeypatch):
    monkeypatch.setenv("MAP_STORY_GA_MEASUREMENT_ID", "G-TEST123456")
    monkeypatch.delenv("MAP_STORY_VOLCENGINE_APM_TOKEN", raising=False)
    monkeypatch.delenv("VOLCENGINE_APM_TOKEN", raising=False)

    html = analytics_head_html(page_type="homepage", page_name="首页")

    assert "googletagmanager.com/gtag/js?id=G-TEST123456" in html
    assert "gtag('config', \"G-TEST123456\")" in html


def test_analytics_head_html_includes_volcengine_apm_when_token_is_configured(monkeypatch):
    monkeypatch.delenv("MAP_STORY_GA_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
    monkeypatch.setenv("MAP_STORY_VOLCENGINE_APM_AID", "1002542")
    monkeypatch.setenv("MAP_STORY_VOLCENGINE_APM_TOKEN", "token-demo")
    monkeypatch.setenv("MAP_STORY_VOLCENGINE_APM_ENV", "prod")
    monkeypatch.setenv("STORYMAP_BUILD_VERSION", "build-v1")

    html = analytics_head_html(page_type="profile", page_name="苏轼")

    assert "https://apm.volccdn.com/mars-web/apmplus/web/browser.cn.js" in html
    assert "window.apmPlus('init',{aid:1002542,token:\"token-demo\",pid: window.location.pathname,env:\"prod\",release:\"build-v1\"});" in html
    assert "window.apmPlus('start');" in html
    assert "story_map_page_open" in html
    assert '"page_type": "profile"' in html
    assert '"page_name": "苏轼"' in html
