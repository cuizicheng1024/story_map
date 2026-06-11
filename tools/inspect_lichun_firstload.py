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
        page.wait_for_timeout(3500)
        payload = page.evaluate(
            """() => {
                const pick = (sel) => document.querySelector(sel);
                const rect = (el) => el ? {
                  x: Math.round(el.getBoundingClientRect().x),
                  y: Math.round(el.getBoundingClientRect().y),
                  w: Math.round(el.getBoundingClientRect().width),
                  h: Math.round(el.getBoundingClientRect().height)
                } : null;
                const testState = window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'
                  ? window.__STORY_MAP_TEST__.getState()
                  : null;
                return {
                  state: testState,
                  mapRect: rect(pick('#map')),
                  mapLibreRect: rect(pick('#map-maplibre')),
                  cesiumRect: rect(pick('#map-cesium')),
                  mapHtml: (pick('#map') || {}).outerHTML ? pick('#map').outerHTML.slice(0, 1200) : '',
                  mapLibreStyle: (() => {
                    const el = pick('#map-maplibre');
                    if (!el) return null;
                    const cs = getComputedStyle(el);
                    return {
                      className: el.className,
                      styleAttr: el.getAttribute('style') || '',
                      position: cs.position,
                      width: cs.width,
                      height: cs.height,
                      top: cs.top,
                      right: cs.right,
                      bottom: cs.bottom,
                      left: cs.left,
                      display: cs.display
                    };
                  })(),
                  timelineRect: rect(pick('[data-pane="timeline"]')),
                  mapPanelRect: rect(pick('[data-pane="map"]')),
                  mapLibreMarkerCount: document.querySelectorAll('#map-maplibre .maplibregl-marker').length,
                  mapLibreCanvasCount: document.querySelectorAll('#map-maplibre canvas').length,
                  amapNodeCount: document.querySelectorAll('#map-maplibre .amap-layer, #map-maplibre .amap-maps, #map-maplibre .amap-marker').length,
                  bootDiag: (pick('#boot-diag') || {}).textContent || ''
                };
            }"""
        )
        page.screenshot(path="artifacts/runtime/lichun_firstload_debug.png", full_page=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
