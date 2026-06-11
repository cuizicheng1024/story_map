#!/usr/bin/env python3

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> int:
    url = "http://localhost:8765/%E6%9D%8E%E6%98%A5.html#loc=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_function(
            "() => !!window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'",
            timeout=30000,
        )
        page.evaluate("() => window.__STORY_MAP_TEST__.setBasemap('terrain-3d')")
        page.wait_for_timeout(2500)
        payload = page.evaluate(
            """() => {
                const maplibreEl = document.getElementById('map-maplibre');
                const cesiumEl = document.getElementById('map-cesium');
                const boot = document.getElementById('boot-diag');
                const state = window.__STORY_MAP_TEST__.getState();
                return {
                  hasCesiumGlobal: Boolean(window.Cesium),
                  state,
                  bootDiag: boot ? String(boot.textContent || '') : '',
                  maplibreHidden: maplibreEl ? maplibreEl.classList.contains('is-hidden') : null,
                  cesiumHidden: cesiumEl ? cesiumEl.classList.contains('is-hidden') : null,
                  cesiumChildren: cesiumEl ? cesiumEl.childElementCount : null,
                  hasCesiumCanvas: Boolean(document.querySelector('#map-cesium canvas')),
                  hasMapLibreCanvas: Boolean(document.querySelector('#map-maplibre canvas')),
                  debugEvents: Array.isArray(window.__STORY_MAP_DEBUG_EVENTS__)
                    ? window.__STORY_MAP_DEBUG_EVENTS__.slice(-20)
                    : []
                };
            }"""
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
