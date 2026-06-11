#!/usr/bin/env python3

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> int:
    url = "http://localhost:8765/%E6%9D%8E%E6%98%A5.html?geovisToken=invalid-token#loc=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.route("**/*geovisearth.com/**", lambda route: route.abort())
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_function(
            "() => !!window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'",
            timeout=30000,
        )
        page.wait_for_timeout(5000)
        before = page.evaluate(
            """() => ({
                state: window.__STORY_MAP_TEST__.getState(),
                bootDiag: (document.getElementById('boot-diag') || {}).textContent || '',
                hasAMap: Boolean(window.AMap),
                debugEvents: Array.isArray(window.__STORY_MAP_DEBUG_EVENTS__) ? window.__STORY_MAP_DEBUG_EVENTS__.slice(-20) : []
            })"""
        )
        page.evaluate("() => window.__STORY_MAP_TEST__.setBasemap('imagery')")
        page.wait_for_timeout(1000)
        imagery = page.evaluate("() => window.__STORY_MAP_TEST__.getState()")
        page.evaluate("() => window.__STORY_MAP_TEST__.setBasemap('terrain')")
        page.wait_for_timeout(800)
        after_terrain = page.evaluate(
            """() => ({
                state: window.__STORY_MAP_TEST__.getState(),
                bootDiag: (document.getElementById('boot-diag') || {}).textContent || ''
            })"""
        )
        print(json.dumps({"before": before, "imagery": imagery, "after_terrain": after_terrain}, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
