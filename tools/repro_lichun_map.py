#!/usr/bin/env python3

from __future__ import annotations

from playwright.sync_api import sync_playwright


def main() -> int:
    url = "http://127.0.0.1:8765/%E6%9D%8E%E6%98%A5.html#loc=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#map .maplibregl-canvas", timeout=30000)
        page.wait_for_function(
            "() => !!window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'",
            timeout=30000,
        )
        print("default=", page.evaluate("() => window.__STORY_MAP_TEST__.getState()"))
        print("focus0=", page.evaluate("() => window.__STORY_MAP_TEST__.focusIndex(0)"))
        page.wait_for_timeout(2500)
        print("after_focus0=", page.evaluate("() => window.__STORY_MAP_TEST__.getState()"))
        print("to_3d=", page.evaluate("() => window.__STORY_MAP_TEST__.setBasemap('terrain-3d')"))
        page.wait_for_timeout(8000)
        print("after_3d=", page.evaluate("() => window.__STORY_MAP_TEST__.getState()"))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
