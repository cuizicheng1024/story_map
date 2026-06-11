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
        page.wait_for_timeout(3000)
        data = page.evaluate(
            """() => {
                const summarize = (selector) => Array.from(document.querySelectorAll(selector)).map((el, idx) => {
                    const r = el.getBoundingClientRect();
                    return {
                        idx,
                        text: (el.innerText || el.textContent || '').trim().slice(0, 80),
                        className: el.className,
                        left: Math.round(r.left),
                        top: Math.round(r.top),
                        width: Math.round(r.width),
                        height: Math.round(r.height),
                        display: getComputedStyle(el).display,
                        opacity: getComputedStyle(el).opacity,
                        transform: el.style.transform || ''
                    };
                });
                return {
                    state: window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'
                        ? window.__STORY_MAP_TEST__.getState()
                        : null,
                    markers: summarize('#map-maplibre .maplibregl-marker'),
                    pointCores: summarize('#map-maplibre .map-point-core'),
                    endpoints: summarize('#map-maplibre .map-endpoint-marker'),
                    labels: summarize('#map-maplibre .map-point-label'),
                    arrows: summarize('#map-maplibre .map-segment-arrow'),
                };
            }"""
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
