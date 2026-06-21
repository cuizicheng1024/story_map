#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

file_path = Path(__file__).resolve()
REPO_ROOT = file_path.parents[2] if file_path.parent.name == "debug" else file_path.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storymap.script.project_paths import person_name_from_filename, story_artifacts_dir_path

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "缺少 playwright 依赖，请先在测试虚拟环境中安装：python -m pip install playwright"
    ) from exc


MAP_MODES = [
    ("vector", "矢量图"),
    ("imagery", "影像图"),
    ("terrain", "地形晕渲图"),
    ("terrain-3d", "Terrain-3D"),
]


def _extract_export_data(html_path: Path) -> Dict[str, Any]:
    text = html_path.read_text(encoding="utf-8")
    match = re.search(r"const data\s*=\s*(\{[\s\S]*?\})\s*;\s*window\.__EXPORT_DATA__", text)
    if not match:
        raise ValueError(f"未找到导出数据: {html_path}")
    return json.loads(match.group(1))


def _candidate_pages(artifacts_dir: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for html_path in sorted(artifacts_dir.glob("*.html")):
        if html_path.name == "index.html":
            continue
        try:
            data = _extract_export_data(html_path)
        except Exception:
            continue
        locations = data.get("locations") or []
        if not isinstance(locations, list) or len(locations) < 1:
            continue
        items.append(
            {
                "person": person_name_from_filename(html_path.name),
                "file": html_path.name,
                "locations": len(locations),
            }
        )
    return items


def _new_people_names() -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--", "storymap/examples/story", "artifacts/story_map"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
    except Exception:
        return set()
    result: set[str] = set()
    for raw_item in bytes(proc.stdout or b"").split(b"\0"):
        if not raw_item:
            continue
        status = raw_item[:2].decode("utf-8", errors="ignore")
        if status not in {"??", "A ", "AM"}:
            continue
        path_text = raw_item[3:].decode("utf-8", errors="ignore").strip()
        if path_text.endswith(".md") and "storymap/examples/story/" in path_text:
            result.add(Path(path_text).stem)
        elif path_text.endswith(".html") and "artifacts/story_map/" in path_text:
            result.add(person_name_from_filename(Path(path_text).name))
    return {name for name in result if str(name or "").strip()}


def _sample_candidates(candidates: List[Dict[str, Any]], count: int, rng: random.Random) -> List[Dict[str, Any]]:
    if count <= 0:
        return []
    new_names = _new_people_names()
    new_candidates = [item for item in candidates if str(item.get("person") or "") in new_names]
    existing_candidates = [item for item in candidates if str(item.get("person") or "") not in new_names]
    if count == 3 and new_candidates and len(existing_candidates) >= 2:
        sampled: List[Dict[str, Any]] = []
        sampled.extend(rng.sample(existing_candidates, 2))
        sampled.extend(rng.sample(new_candidates, 1))
        rng.shuffle(sampled)
        return sampled
    return rng.sample(candidates, count)


def _wait_for_page_ready(page) -> None:
    page.wait_for_selector("#map .maplibregl-canvas", timeout=30000)
    try:
        page.wait_for_function(
            "() => !!window.__STORY_MAP_TEST__ && typeof window.__STORY_MAP_TEST__.getState === 'function'",
            timeout=30000,
        )
    except PlaywrightTimeoutError as exc:
        boot_diag = page.evaluate(
            """() => {
                const el = document.getElementById('boot-diag');
                return el ? String(el.textContent || '').trim() : '';
            }"""
        )
        detail = f"boot-diag={boot_diag}" if boot_diag else "boot-diag=<empty>"
        raise PlaywrightTimeoutError(f"页面测试钩子未就绪: {detail}") from exc


def _prime_default_vector(page, focus_index: int) -> None:
    page.evaluate(
        """(idx) => {
            window.__STORY_MAP_TEST__.focusIndex(idx);
        }""",
        focus_index,
    )
    try:
        page.wait_for_function(
            """(idx) => {
                const api = window.__STORY_MAP_TEST__;
                if (!api || typeof api.getState !== 'function') return false;
                const state = api.getState();
                return state.mapLayerType === 'vector' && state.activeIndex === idx;
            }""",
            arg=focus_index,
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(1200)


def _switch_mode_and_focus(page, mode_id: str, focus_index: int, location_count: int) -> Dict[str, Any]:
    mode_ready_timeout = 35000 if mode_id == "terrain-3d" else 20000
    linkage_timeout = 15000 if mode_id == "terrain-3d" else 15000
    wait_stage_errors: List[str] = []
    page.evaluate(
        """(modeId) => {
            window.__STORY_MAP_TEST__.setBasemap(modeId);
        }""",
        mode_id,
    )
    try:
        page.wait_for_function(
            """([modeId, locationCount]) => {
                const api = window.__STORY_MAP_TEST__;
                if (!api || typeof api.getState !== 'function') return false;
                const state = api.getState();
                if (state.mapLayerType !== modeId) return false;
                if (modeId === 'terrain-3d') return state.engine === 'cesium' && Number(state.pitch || 0) >= 20;
                if (state.engine !== 'maplibre') return false;
                const segments = Array.isArray(state.segmentStates) ? state.segmentStates : [];
                return locationCount <= 1 ? true : segments.length > 0;
            }""",
            arg=[mode_id, location_count],
            timeout=mode_ready_timeout,
        )
    except PlaywrightTimeoutError as exc:
        wait_stage_errors.append(f"mode_ready_timeout: {exc}")
        page.wait_for_timeout(1200)
    page.evaluate(
        """(idx) => {
            window.__STORY_MAP_TEST__.focusIndex(idx);
        }""",
        focus_index,
    )
    try:
        page.wait_for_function(
            """([modeId, idx]) => {
                const api = window.__STORY_MAP_TEST__;
                if (!api || typeof api.getState !== 'function') return false;
                const state = api.getState();
                return state.mapLayerType === modeId && state.activeIndex === idx;
            }""",
            arg=[mode_id, focus_index],
            timeout=15000,
        )
    except PlaywrightTimeoutError as exc:
        wait_stage_errors.append(f"focus_timeout: {exc}")
        page.wait_for_timeout(1200)
    try:
        page.wait_for_function(
            """([modeId, idx]) => {
                const api = window.__STORY_MAP_TEST__;
                if (!api || typeof api.getState !== 'function') return false;
                const state = api.getState();
                if (state.mapLayerType !== modeId || state.activeIndex !== idx) return false;
                if (modeId === 'terrain-3d') {
                    if (state.engine !== 'cesium' || Number(state.pitch || 0) < 20) return false;
                } else if (state.engine !== 'maplibre' || Number(state.pitch || 0) > 5) {
                    return false;
                }
                const segments = Array.isArray(state.segmentStates) ? state.segmentStates : [];
                if (!segments.length || idx <= 0) return true;
                const activeSegment = idx - 1;
                const current = segments.find((item) => Number(item && item.idx) === activeSegment);
                const future = segments.find((item) => Number(item && item.idx) === activeSegment + 1);
                if (!current) return false;
                const currentOpacity = Number(current.lineOpacity || 0);
                const futureOpacity = future ? Number(future.lineOpacity || 0) : 0;
                return currentOpacity > futureOpacity;
            }""",
            arg=[mode_id, focus_index],
            timeout=linkage_timeout,
        )
    except PlaywrightTimeoutError as exc:
        wait_stage_errors.append(f"linkage_timeout: {exc}")
        page.wait_for_timeout(1200)
    state = page.evaluate("() => window.__STORY_MAP_TEST__.getState()")
    if wait_stage_errors:
        state["_wait_stage_errors"] = wait_stage_errors
    return state


def _assert_linkage(state: Dict[str, Any], focus_index: int) -> Dict[str, Any]:
    segments = list(state.get("segmentStates") or [])
    if not segments or focus_index <= 0:
        return {"ok": True, "reason": "segment_skip"}
    active_segment = focus_index - 1
    current = next((item for item in segments if int(item.get("idx", -1)) == active_segment), None)
    future = next((item for item in segments if int(item.get("idx", -1)) == active_segment + 1), None)
    if not current:
        return {"ok": False, "reason": "missing_current_segment"}
    current_opacity = float(current.get("lineOpacity") or 0)
    future_opacity = float(future.get("lineOpacity") or 0) if future else 0.0
    return {
        "ok": current_opacity > future_opacity,
        "reason": "current_vs_future_opacity",
        "current_opacity": current_opacity,
        "future_opacity": future_opacity,
    }


def _assert_terrain_mode(state: Dict[str, Any], mode_id: str) -> Dict[str, Any]:
    pitch = float(state.get("pitch") or 0)
    if mode_id == "terrain-3d":
        return {"ok": str(state.get("engine") or "") == "cesium" and pitch >= 20, "pitch": pitch}
    return {"ok": pitch <= 5, "pitch": pitch}


def run(args: argparse.Namespace) -> int:
    artifacts_dir = story_artifacts_dir_path()
    candidates = _candidate_pages(artifacts_dir)
    if len(candidates) < args.count:
        raise SystemExit(f"可抽样人物不足：需要 {args.count} 个，当前仅 {len(candidates)} 个")

    rng = random.Random(args.seed if args.seed is not None else int(time.time()))
    sampled = _sample_candidates(candidates, args.count, rng)

    report_dir = Path(args.output_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for item in sampled:
            page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
            file_name = str(item["file"])
            person = str(item["person"])
            url = f"{args.base_url.rstrip('/')}/{quote(file_name)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            _wait_for_page_ready(page)
            focus_index = 0 if int(item["locations"]) <= 1 else max(1, int(item["locations"]) // 2)
            _prime_default_vector(page, focus_index)
            mode_results = []
            for mode_id, mode_label in MAP_MODES:
                try:
                    state = _switch_mode_and_focus(page, mode_id, focus_index, int(item["locations"]))
                    linkage = _assert_linkage(state, focus_index)
                    terrain = _assert_terrain_mode(state, mode_id)
                    mode_results.append(
                        {
                            "mode": mode_id,
                            "label": mode_label,
                            "ok": bool(linkage["ok"] and terrain["ok"]),
                            "linkage": linkage,
                            "terrain": terrain,
                            "engine": state.get("engine"),
                            "wait_stage_errors": list(state.get("_wait_stage_errors") or []),
                        }
                    )
                except PlaywrightTimeoutError as exc:
                    mode_results.append(
                        {
                            "mode": mode_id,
                            "label": mode_label,
                            "ok": False,
                            "error": f"timeout: {exc}",
                        }
                    )
            results.append(
                {
                    "person": person,
                    "file": file_name,
                    "url": url,
                    "focus_index": focus_index,
                    "modes": mode_results,
                    "sample_bucket": "new" if person in _new_people_names() else "existing",
                }
            )
            page.close()
        browser.close()

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": args.seed,
        "base_url": args.base_url,
        "sampled": [item["person"] for item in sampled],
        "results": results,
    }
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT: {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="随机抽取人物页并检查四个底图显示效果")
    parser.add_argument("--count", type=int, default=3, help="抽样人物数量")
    parser.add_argument("--seed", type=int, default=None, help="随机种子，便于复现")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="本地预览服务地址")
    parser.add_argument(
        "--output-dir",
        default=str(Path("artifacts") / "runtime" / "basemap_smoke"),
        help="测试报告输出目录",
    )
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
