import importlib
import typing

from tests_support import REPO_ROOT

TEMPLATE_PATH = REPO_ROOT / "storymap" / "script" / "profile" / "templates" / "profile_page.html"

from storymap.script.cli import story_map
from storymap.script.core.artifacts import _extract_export_data_from_html
from storymap.script.profile import builder as profile_builder
from storymap.script.profile import renderer
from storymap.script.profile.renderer import render_profile_html
def _profile_app_js():
    """Bundled profile app JS (compiled from React template)."""
    from pathlib import Path
    import json
    artifacts = Path(__file__).resolve().parent.parent.parent / "artifacts" / "story_map" / "static" / "profile-app.js"
    if artifacts.exists():
        return artifacts.read_text(encoding="utf-8")
    return ""

def test_render_profile_html_builds_person_redirects_from_filtered_story_people(monkeypatch):
    captured = {}

    monkeypatch.setattr(renderer, "story_person_names", lambda _dir=None: ["苏轼"])
    def _fake_person_redirects(names):
        captured["names"] = list(names)
        return {"苏东坡": "苏轼"}

    monkeypatch.setattr(renderer, "person_redirects", _fake_person_redirects)

    render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert captured["names"] == ["苏轼"]

def test_render_profile_html_omits_google_analytics_snippet_without_explicit_config(monkeypatch):
    monkeypatch.delenv("MAP_STORY_GA_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)

    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "googletagmanager.com/gtag/js?id=" not in html
    assert "gtag('config'," not in html

def test_render_profile_html_includes_google_analytics_snippet_when_explicitly_configured(monkeypatch):
    monkeypatch.setenv("MAP_STORY_GA_MEASUREMENT_ID", "G-TEST123456")

    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "googletagmanager.com/gtag/js?id=G-TEST123456" in html
    assert "gtag('config', \"G-TEST123456\")" in html

def test_render_profile_html_precompiles_profile_app_and_omits_runtime_babel_script():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert '<script src="./vendor/babel.min.js"></script>' not in html
    assert '<script type="text/babel"' not in html
    assert "window.__EXPORT_DATA__ = data;" in html
def test_render_profile_html_omits_legacy_placeholder_api_base(monkeypatch):
    monkeypatch.setenv("MAP_STORY_API_BASE", "http://legacy.example")

    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "window.MAP_STORY_API_BASE=" not in html

def test_runtime_page_config_html_omits_debug_config_without_explicit_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("MAP_STORY_ENABLE_RUNTIME_DEBUG_CONFIG", raising=False)
    monkeypatch.delenv("STORY_MAP_ENABLE_RUNTIME_DEBUG_CONFIG", raising=False)
    monkeypatch.setattr(renderer, "_REPO_ROOT", tmp_path)
    dbg_dir = tmp_path / ".dbg"
    dbg_dir.mkdir(parents=True)
    (dbg_dir / "map-loading-blank.env").write_text(
        "DEBUG_SERVER_URL=http://127.0.0.1:7777/event\nDEBUG_SESSION_ID=map-loading-blank\n",
        encoding="utf-8",
    )

    html = renderer._runtime_page_config_html()

    assert "__STORY_MAP_DEBUG_SERVER__" not in html
    assert "__STORY_MAP_DEBUG_SESSION_ID__" not in html

def test_runtime_page_config_html_includes_debug_config_after_explicit_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("MAP_STORY_ENABLE_RUNTIME_DEBUG_CONFIG", "1")
    monkeypatch.setattr(renderer, "_REPO_ROOT", tmp_path)
    dbg_dir = tmp_path / ".dbg"
    dbg_dir.mkdir(parents=True)
    (dbg_dir / "map-loading-blank.env").write_text(
        "DEBUG_SERVER_URL=http://127.0.0.1:7777/event\nDEBUG_SESSION_ID=map-loading-blank\n",
        encoding="utf-8",
    )

    html = renderer._runtime_page_config_html()

    assert 'window.__STORY_MAP_DEBUG_SERVER__="http://127.0.0.1:7777/event";' in html
    assert 'window.__STORY_MAP_DEBUG_SESSION_ID__="map-loading-blank";' in html

def test_runtime_page_config_html_uses_selected_debug_session_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAP_STORY_ENABLE_RUNTIME_DEBUG_CONFIG", "1")
    monkeypatch.setenv("MAP_STORY_RUNTIME_DEBUG_SESSION", "map-blank-v2")
    monkeypatch.setattr(renderer, "_REPO_ROOT", tmp_path)
    dbg_dir = tmp_path / ".dbg"
    dbg_dir.mkdir(parents=True)
    (dbg_dir / "map-loading-blank.env").write_text(
        "DEBUG_SERVER_URL=http://127.0.0.1:7777/event\nDEBUG_SESSION_ID=map-loading-blank\n",
        encoding="utf-8",
    )
    (dbg_dir / "map-blank-v2.env").write_text(
        "DEBUG_SERVER_URL=http://127.0.0.1:7777/event\nDEBUG_SESSION_ID=map-blank-v2\n",
        encoding="utf-8",
    )

    html = renderer._runtime_page_config_html()

    assert 'window.__STORY_MAP_DEBUG_SESSION_ID__="map-blank-v2";' in html

def test_render_profile_html_does_not_inline_public_map_credentials(monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "test-amap-key")
    monkeypatch.setenv("AMAP_SECURITY", "test-amap-security")

    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert 'window.AMAP_KEY="test-amap-key";' not in html
    assert 'window.AMAP_SECURITY="test-amap-security";' not in html

def test_profile_template_signature_covers_render_dependency_sources():
    deps = renderer.profile_render_dependency_paths()
    names = {path.name for path in deps}

    assert "person_registry.py" in names
    assert "profile_builder.py" in names
    assert "generate_pure_story_map.py" in names
    assert not any(str(path).endswith("storymap/script/templates/profile_page.html") for path in deps)
    assert not any(str(path).endswith("storymap/script/templates/design_tokens.css") for path in deps)

def test_build_info_panel_html_initializes_wrapper():
    html = renderer.build_info_panel_html("测试人物", {"朝代": "西汉", "身份": "外交使者"})

    assert 'class="bio-panel"' in html
    assert "西汉" in html
    assert "外交使者" in html

def test_render_profile_html_falls_back_to_raw_knowledge_graph(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    renderer._build_stellar_home_fallback.cache_clear()
    renderer.invalidate_graph_service_cache()
    monkeypatch.setattr(renderer, "STELLAR_HOME_DATA_JSON", REPO_ROOT / "artifacts" / "story_map" / "__missing_home_data__.json")
    payload = {
        "nodes": [
            {
                "person": "张骞",
                "file": "张骞.html",
                "dynasty": "西汉",
                "birth_year": -164,
                "death_year": -114,
                "domain_tags": ["外交"],
                "main_role_label": "外交家",
                "birthplace": "城固",
                "birthplace_modern": "陕西城固",
                "quote": "凿空西域。",
                "review": "开拓丝路的关键人物。",
                "foreign_name": "",
                "has_story": True,
            },
            {
                "person": "汉武帝",
                "file": "汉武帝.html",
                "dynasty": "西汉",
                "birth_year": -156,
                "death_year": -87,
                "domain_tags": ["政治"],
                "main_role_label": "皇帝",
                "birthplace": "长安",
                "birthplace_modern": "陕西西安",
                "quote": "雄才大略。",
                "review": "西汉强盛时期的重要统治者。",
                "foreign_name": "",
                "has_story": True,
            },
        ],
        "edges": [{"a": 0, "b": 1, "type": "bio", "label": "君臣", "confidence": 0.88}],
    }
    monkeypatch.setattr(renderer, "load_home_graph_payload", lambda _path=None: payload)

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
    related_nodes = related.get("nodes") or []
    han_wu_di = next((node for node in related_nodes if str(node.get("name") or "") == "汉武帝"), None)

    assert len(related_nodes) >= 1
    assert han_wu_di is not None
    assert "birth_year" in han_wu_di
    assert "death_year" in han_wu_di
    assert "quote" in han_wu_di
    assert "review" in han_wu_di
    assert "main_role_label" in han_wu_di
    assert "birthplace" in han_wu_di
    assert "birthplace_modern" in han_wu_di
    assert "foreign_name" in han_wu_di
    assert "domain_tags" in han_wu_di
    assert "has_story" in han_wu_di

def test_render_profile_html_prefers_shared_graph_service_payload(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    renderer._build_stellar_home_fallback.cache_clear()
    renderer.invalidate_graph_service_cache()
    payload = {
        "nodes": [
            {
                "person": "张骞",
                "file": "张骞.html",
                "dynasty": "西汉",
                "birth_year": -164,
                "death_year": -114,
                "domain_tags": ["外交"],
            },
            {
                "person": "汉武帝",
                "file": "汉武帝.html",
                "dynasty": "西汉",
                "birth_year": -156,
                "death_year": -87,
                "domain_tags": ["政治"],
            },
        ],
        "edges": [{"a": 0, "b": 1, "type": "bio", "label": "君臣", "confidence": 0.88}],
    }
    monkeypatch.setattr(renderer, "load_home_graph_payload", lambda _path=None: payload)

    html = render_profile_html(
        {
            "person": {"name": "张骞", "dynasty": "西汉"},
            "locations": [],
            "highlights": {},
            "markdown": "# 张骞\n\n张骞出使西域。",
        }
    )

    related = (_extract_export_data_from_html(html).get("relatedGraph") or {}).get("nodes") or []
    assert any(str(item.get("name") or "") == "汉武帝" for item in related)

def test_related_people_graph_prefers_graph_service_result(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    monkeypatch.setattr(
        renderer,
        "get_related_people_graph",
        lambda person, markdown="", limit=6: {
            "center": {"name": str(person.get("name") or ""), "isCenter": True},
            "nodes": [{"name": str(person.get("name") or ""), "isCenter": True}, {"name": "汉武帝", "isCenter": False}],
            "links": [{"source": str(person.get("name") or ""), "target": "汉武帝", "label": "君臣"}],
        },
    )
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: (_ for _ in ()).throw(AssertionError("should not fallback")))

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "张骞", "dynasty": "西汉"},
            "markdown": "# 张骞\n\n张骞出使西域。",
        }
    )

    assert any(str(node.get("name") or "") == "汉武帝" for node in (related.get("nodes") or []))

def test_related_people_graph_falls_back_when_graph_service_raises(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    payload = {
        "nodes": [
            {"person": "张骞", "file": "张骞.html", "dynasty": "西汉"},
            {"person": "汉武帝", "file": "汉武帝.html", "dynasty": "西汉"},
        ],
        "edges": [{"a": 0, "b": 1, "type": "bio", "label": "君臣", "confidence": 0.88}],
    }
    monkeypatch.setattr(
        renderer,
        "get_related_people_graph",
        lambda person, markdown="", limit=6: (_ for _ in ()).throw(RuntimeError("neo4j unavailable")),
    )
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: payload)

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "张骞", "dynasty": "西汉"},
            "markdown": "# 张骞\n\n张骞出使西域。",
        }
    )

    assert any(str(node.get("name") or "") == "汉武帝" for node in (related.get("nodes") or []))
def test_profile_template_uses_natural_ambiguous_birthplace_note_copy():
    template_source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "出生地说法：" in template_source
def test_profile_template_only_uses_fallback_overlay_when_maplibre_artifacts_are_missing():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const isValidMapCoordinatePair = (pair) => {" in html
    assert "const expectedPointLayerIds = getExpectedPointLayerIds();" in html
    assert "const expectedLineIds = getExpectedSegmentLayerIds();" in html
    assert "const hasPointArtifacts = !expectedPointLayerIds.length || (" in html
    assert "map.getLayer(id)" in html
    assert "const hasSegmentArtifacts = !expectedLineIds.length || expectedLineIds.every((id) => {" in html
    assert "if (hasRenderableOverlayArtifacts()) {" in html
    assert "map.on('movestart', () => {" in html
    assert "map.on('zoomstart', () => {" in html
    assert "scheduleFallbackOverlayRender('moveend');" in html
    assert "scheduleFallbackOverlayRender('zoomend');" in html
    assert 'pointMarkup.push(`<text x="${x.toFixed(2)}"' in html
    assert 'paint-order="stroke">${idx + 1}</text>' in html

def test_static_site_notice_hides_on_localhost(monkeypatch):
    monkeypatch.setenv("MAP_STORY_STATIC_SITE", "1")
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert 'id="site-mode-notice"' in html
    assert "const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');" in html
    assert "const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);" in html
    assert "if (notice) notice.style.display = 'none';" in html
def test_amap_fallback_complete_event_refreshes_overlays():
    """Regression test for B1 (map-loading-blank): after the AMap fallback
    fires 'complete', overlays (markers/segments) must be re-synced so the
    first frame after tiles load is not blank."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # The complete handler must trigger a resize + setActive + refreshLabels
    assert "map.on('complete', () => {" in html
    assert "amap complete refresh" in html
    assert "amapControllerRef.current.setActive(activeIndexRef.current)" in html
    assert "amapControllerRef.current.refreshLabels(activeIndexRef.current)" in html
    assert "typeof map.resize === 'function'" in html

def test_setActive_is_idempotent_for_same_active_index():
    """Regression test for B3 + B6 (wanganshi-marker-flicker):
    setActive should short-circuit when called with the same active index
    so it does not flash repeatedly."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # The maplibre setActive implementation should compare against lastActiveIdx
    assert "lastActiveIdx" in html
    assert "if (typeof activeIdx === 'number' && activeIdx === lastActiveIdx) {" in html

def test_overlay_rebuild_loop_has_backoff_guard():
    """Regression test for B2 + B5 (map-loading-stuck): the overlay rebuild
    loop must have a counter/breaker so styledata storms cannot deadlock it."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "overlayRebuildMutedUntil" in html
    assert "overlayRebuildInProgress" in html
    # There should be a hard cap on consecutive rebuilds so the loop dies
    # instead of starving the UI thread.
    assert "overlayRebuildMaxConsecutive" in html
    assert "if (consecutiveOverlayRebuilds >= overlayRebuildMaxConsecutive)" in html

def test_geo_vis_token_error_dispatches_retry_geovis_action():
    """Regression test for B4: when GeoVis token is missing the notice must
    expose a retry-geovis action so the user can recover without a hard
    page reload."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "retry-geovis" in html
    # The retry handler should dispatch and re-attempt ensureMapLibre
    assert "kind === 'retry-geovis'" in html
    assert "ensureMapLibre" in html or "ensureConfig" in html
    # And the action label is visible to the user
    assert "恢复 GeoVis" in html

def test_global_error_handler_distinguishes_opaque_cross_origin_errors():
    """Regression test for B7 (profile-debugemit-boot): the global error
    handler must tag opaque 'Script error.' events so triage is possible
    instead of dumping empty payloads into debug logs."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "addEventListener('error', (event) => {" in html
    assert "opaqueCrossOrigin" in html
    assert "crossorigin=\"anonymous\"" in html
    # Promise rejections are a separate, more common failure mode in this app
    assert "addEventListener('unhandledrejection', (event) => {" in html
    assert "unhandled rejection captured" in html

def test_static_site_avatar_prefers_relative_portraits_path():
    """Regression test for B8 (production-map-fail): in static production
    builds the FastAPI /portrait/ endpoint returns 404. The page must use
    the relative ./portraits/<name>.jpg cache directory instead."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "MAP_STORY_STATIC_SITE === true" in html
    assert "./portraits/" in html
    # Sanity: we still keep the API path for dev runs
    assert "/portrait/${encodeURIComponent(personName)}" in html

def test_pulse_marker_css_promotes_to_own_layer():
    """Stage 3 / P1: pulse markers must declare will-change + contain so
    frequent focus events stay at 60fps without repainting the parent."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".map-pulse-marker {" in html
    # The two declarations should appear inside the .map-pulse-marker rule
    # block (rather than as global defaults).
    pulse_idx = html.index(".map-pulse-marker {")
    next_rule = html.index("}", pulse_idx)
    pulse_block = html[pulse_idx:next_rule]
    assert "will-change: transform, opacity" in pulse_block
    assert "contain: layout style paint" in pulse_block

def test_map_point_core_declares_will_change_for_layer_promotion():
    """Stage 3 / P4: per-point markers must declare will-change so the
    active/inactive transition does not trigger layout/paint on the map
    canvas container."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".map-point-core {" in html
    point_idx = html.index(".map-point-core {")
    next_rule = html.index("}", point_idx)
    point_block = html[point_idx:next_rule]
    assert "will-change" in point_block
    assert "contain:" in point_block

def test_vendor_scripts_have_preload_hints_for_lcp():
    """Stage 3 / P2: vendor scripts should be preloaded so the browser
    starts fetching them in parallel with the HTML parser."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Preact core + hooks + compat are preloaded for runtime use.
    # tailwindcss.js has been replaced by build-time compiled static/tailwind.css.
    assert 'rel="preload" href="./vendor/preact.min.js" as="script"' in html
    assert 'rel="preload" href="./vendor/preact-hooks.min.js" as="script"' in html
    assert 'rel="preload" href="./vendor/preact-compat.production.min.js" as="script"' in html
    # Sanity: preloads come before the actual script tags
    preload_pos = html.index('rel="preload" href="./vendor/preact.min.js"')
    script_pos = html.index('<script src="./vendor/preact.min.js"></script>')
    assert preload_pos < script_pos
    # tailwindcss.js must NOT be present in the template
    assert 'tailwindcss.js' not in html

def test_set_active_paint_is_coalesced_with_request_animation_frame():
    """Stage 3 / P3: setActive must defer the heavy paint work to the
    next animation frame so multiple calls in the same frame collapse
    into one composite update."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "setActivePaintRaf" in html
    assert "performSetActivePaint" in html
    assert "setPaintIfChanged" in html
    # The cached paint helper should compare against the prior value to
    # skip redundant setPaintProperty calls.
    assert "lastSegmentPaint" in html
    # The cache must be flushed when overlays are rebuilt so it does not
    # leak stale layer ids.
    assert "flushSegmentPaintCache" in html

def test_pulse_marker_uses_element_pool():
    """Stage 3 / P1: pulse marker DOM elements should be pooled (limit 3)
    so the focus hot-path does not allocate a fresh <div> + maplibre.Marker
    every click."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "PULSE_POOL_LIMIT = 3" in html
    assert "acquirePulseElement" in html
    assert "releasePulseElement" in html
    assert "pulseElementPool" in html

def test_prefers_reduced_motion_disables_animations():
    """UX1: a global media query must disable keyframe animations and
    transitions for users who opted out of motion."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "@media (prefers-reduced-motion: reduce)" in html
    # There may be multiple reduce-motion blocks (UX1 + UX3 skeleton).
    # Gather them all and assert each critical selector is covered.
    blocks = []
    cursor = 0
    needle = "@media (prefers-reduced-motion: reduce)"
    while True:
        idx = html.find(needle, cursor)
        if idx < 0:
            break
        # naive but adequate: find the first closing brace pair after idx.
        # The block ends at the next "}" on the same indentation level.
        end = html.find("\n}", idx)
        if end < 0:
            break
        blocks.append(html[idx:end + 2])
        cursor = end + 2
    combined = "\n".join(blocks)
    for selector in [".map-pulse-marker", ".story-marker", ".map-point-core", ".selected-point-pin"]:
        assert selector in combined, f"selector {selector} missing from reduced-motion blocks: {combined!r}"
    # Skeleton must also be covered
    assert ".map-lazy-title.is-skeleton" in combined

def test_focus_uses_flyto_with_custom_easing():
    """UX2: focus on a trajectory point must animate the camera via flyTo
    with a custom easing curve instead of teleporting with jumpTo."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "map.flyTo({" in html
    assert "duration: 700" in html
    assert "easing:" in html
    # Sanity: prefers-reduced-motion falls back to jumpTo
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in html
def test_active_marker_has_lift_transition():
    """UX4: the active marker must lift + slightly scale on activation so
    users can spot the focused point in their peripheral vision."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".story-marker.is-active .story-marker-dot," in html
    assert ".story-marker.is-active .story-marker-badge {" in html
    assert "translateY(-2px) scale(1.08)" in html

def test_keyboard_navigation_supports_home_end_and_global_listener():
    """UX5: timeline must respond to ArrowLeft/Right + Home/End, and a
    global keydown listener must route those keys when no input is
    focused."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "event.key === 'Home'" in html
    assert "event.key === 'End'" in html
    assert "window.addEventListener('keydown', onKeyDown);" in html
    assert "isContentEditable" in html

def test_markers_outside_viewport_are_marked_for_culling():
    """UX8: the moveend handler must tag off-viewport markers so CSS can
    skip painting them — a cheap optimisation for large trajectories."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "data-out-of-view" in html
    assert "bounds.contains(ll)" in html or "bounds.contains" in html
    assert "visibility: hidden;" in html

def test_map_preconnect_warms_amap_and_geovis_cdns():
    """O1: the head must preconnect + dns-prefetch the map SDK CDNs so
    the first SDK fetch doesn't pay the handshake cost on click."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'rel="preconnect" href="https://webapi.amap.com"' in html
    assert 'rel="preconnect" href="https://atlasapi.geovisearth.com"' in html
    assert 'rel="dns-prefetch" href="https://webapi.amap.com"' in html
    assert 'rel="dns-prefetch" href="https://atlasapi.geovisearth.com"' in html

def test_segment_visual_state_supports_time_gradient_fade():
    """O2: getSegmentVisualState must compute a time-faded base color
    so users can read chronology along the trajectory without studying
    dates."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "timeFadedBaseColor" in html
    assert "ageRatio" in html
    assert "totalSegments" in html
    assert "mixHex(normalBaseColor, '#ffffff'" in html

def test_segment_direction_arrows_are_pooled_per_segment_index():
    """O3: each segment gets a directional arrow at its midpoint,
    aligned to the dominant edge bearing, and arrows are pooled by
    segment index so repeated rebuilds don't churn DOM."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".map-segment-arrow" in html
    assert "segmentArrowMarkersRef" in html
    assert "computeSegmentBearing" in html
    assert "ensureSegmentArrow" in html
    assert "rotate(" in html

def test_markers_are_keyboard_focusable_and_announced_via_aria_live():
    """O4: markers must be keyboard-focusable (tabindex=0) with an
    aria-label, and switching the active point must update an ARIA live
    region so screen readers catch up."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # The DOM API is called with single quotes in the JS source; check
    # for either quote style to stay forward-compatible.
    assert ("setAttribute('tabindex', '0')" in html
            or 'setAttribute("tabindex", "0")' in html)
    assert ("setAttribute('aria-label'" in html
            or 'setAttribute("aria-label"' in html)
    assert 'aria-live' in html
    assert "story-map-aria-live" in html
    # The ARIA live region is created via setAttribute('role', 'status').
    assert ("setAttribute('role', 'status')" in html
            or 'setAttribute("role", "status")' in html)

def test_active_point_writes_to_url_hash_for_shareable_links():
    """O5: navigating to a new active point must update the URL hash
    via history.replaceState so a refresh / link share restores the
    same view."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "window.history.replaceState" in html
    assert "#loc=" in html
    assert "targetHash" in html

def test_scholar_profile_includes_person_evaluation_prompt():
    """The scholar profile's recommended-question set must include a
    人物评价 (person evaluation) prompt so users can ask scholars to
    comment on contemporaries / predecessors."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "人物评价" in html
    # The scholar-specific question should reference "同时代" (contemporary)
    # so it surfaces naturally for figures like 孔子 → 老子.
    scholar_idx = html.index("profile === 'scholar'")
    scholar_block = html[scholar_idx:scholar_idx + 1500]
    assert "人物评价" in scholar_block
    # 孔子 should have a custom override that points at 老子's teachings
    # so the user gets the persona-appropriate prompt even before the
    # generic slot fires.
    assert "'孔子'" in html
    assert "你如何看待老子的学说" in html

def test_static_portrait_url_matches_cache_filename_with_unicode_safe_name():
    """The header avatar URL must mirror the on-disk cache file name:
    safeName (where Chinese letters are preserved, matching Python's
    str.isalnum()) + 12-char sha1. Falling back to a non-Unicode-safe
    regex breaks all 27 Wikimedia portraits."""
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "buildStaticPortraitUrl" in html
    # CJK Unified range must be allowed in safeName (孔子 etc.)
    assert "0x4E00 && code <= 0x9FFF" in html
    # sha1 must be computed (sync impl, no window.crypto.subtle assumption)
    assert "sha1Sync" in html
    # Output format must include the digest and a 48-char cap
    assert ".slice(0, 48)" in html
    assert "digest12" in html
    # Extension fallback chain on 404
    assert "endsWith('.jpg')" in html
    assert "endsWith('.png')" in html
    assert "endsWith('.webp')" in html
    assert "endsWith('.svg')" in html

def test_map_initialisation_has_safety_net_timer():
    """B9: when the IntersectionObserver never fires (fixed viewport,
    mocked environment, hidden map container), the map must still
    initialise within ~2.5s so the page never gets stuck on
    "正在加载地图…". A pure static-page lint of the template is
    sufficient here."""
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # The viewport observer must exist (existing behaviour)
    assert "IntersectionObserver" in html
    # AND a deterministic safety net that runs if the observer is
    # never satisfied.
    assert "requestViewportInit('safety-net')" in html
    assert "safetyTimer" in html

def test_map_outside_click_dismisses_location_popup():
    """B10: clicking the empty map area should dismiss the stuck
    location-detail popup. Marker clicks must not trigger it."""
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "setSelectedLoc(null)" in html
    # The outside-click must skip the markers + arrows + glass panel
    # so they don't accidentally close the popup.
    assert ".map-point-label-shell" in html
    assert ".glass-panel" in html
def test_map_html_renderer_type_hints_resolve_for_canonical_person_name():
    registry = importlib.import_module("storymap.script.core.person_registry")
    hints = typing.get_type_hints(registry.canonical_person_name)

    assert "available_names" in hints
    assert hints["return"] is str
def test_related_people_graph_matches_markdown_mentions_with_middle_dot_names(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    payload = {
        "nodes": [
            {
                "person": "甘地",
                "file": "甘地.html",
                "dynasty": "近现代",
            },
            {
                "person": "马丁·路德·金",
                "file": "马丁·路德·金.html",
                "dynasty": "近现代",
            },
        ],
        "edges": [],
    }
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: payload)

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "甘地", "dynasty": "近现代"},
            "markdown": "# 甘地\n\n甘地与马丁·路德·金关系密切。",
        }
    )

    names = [str(node.get("name") or "") for node in (related.get("nodes") or [])]
    assert "马丁·路德·金" in names
def test_load_profile_prefers_work_quote_for_literary_person():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李斯.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "泰山不让土壤" in str(profile["person"].get("quote") or "")
    assert "泰山不让土壤" in str(profile["person"].get("shortReview") or "")
def test_load_profile_prefers_external_literary_review_for_non_literary_person():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "王昭君.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert str(profile["person"].get("shortReview") or "") == "画图省识春风面，环佩空归月夜魂。"

def test_load_profile_prefers_explicit_short_review_for_wu_zhao():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "武则天.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert str(profile["person"].get("shortReview") or "") == "千秋功过，后人评说。"

def test_choose_short_review_prefers_personal_sharp_remark_for_non_literary_fallback():
    review = profile_builder.choose_short_review(
        info={"主要身份": "政治家、将领"},
        locations=[{"quotes": "《奏疏》：“先天下之忧而忧。”；临终慨叹：“大势已去，奈何！”"}],
        work_texts={"奏疏": "先天下之忧而忧。"},
        historical_reviews=[],
        fallback="",
    )

    assert review == "大势已去，奈何！"

def test_choose_short_review_prefers_explicit_short_review_marker():
    review = profile_builder.choose_short_review(
        info={"主要身份": "诗人"},
        locations=[{"quotes": "《将进酒》：“天生我材必有用。”"}],
        work_texts={"将进酒": "天生我材必有用。"},
        historical_reviews=["短评：天才诗人，浪漫主义高峰。", "李白诗风雄奇飘逸。"],
        fallback="",
    )

    assert review == "天才诗人，浪漫主义高峰。"

def test_choose_short_review_prefers_historical_record_before_generic_review():
    review = profile_builder.choose_short_review(
        info={"主要身份": "政治家"},
        locations=[],
        work_texts={},
        historical_reviews=["《汉书》称其为治世能臣。", "后世多称其办事果决。"],
        fallback="",
    )

    assert review == "《汉书》称其为治世能臣。"

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
def test_profile_page_template_places_work_tooltips_above_inline_links():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const WorkTitleWithTooltip = ({ fullTitle, className }) => {" in html
    assert "const [placement, setPlacement] = useState({ vertical: 'up', horizontal: 'left' });" in html
    assert "const horizontal = (spaceRight < tooltipWidth && spaceLeft > spaceRight) ? 'right' : 'left';" in html
    assert "const vertical = (spaceAbove < tooltipHeight + 20 && spaceBelow > spaceAbove) ? 'down' : 'up';" in html
    assert "const [open, setOpen] = useState(false);" in html
    assert "const [portalStyle, setPortalStyle] = useState({ left: 0, top: 0, visibility: 'hidden' });" in html
    assert "ReactDOM.createPortal(" in html
    assert 'className="pointer-events-none fixed z-[1400]' in html
    assert "window.addEventListener('scroll', sync, true);" in html

def test_profile_page_template_contains_fullscreen_and_3d_control_hooks():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "journeyShellRef" in html
    assert "toggleJourneyFullscreen" in html
    assert "exportJourneySnapshot" in html
    assert "const captureCurrentTabFrame = async () => {" in html
    assert "navigator.mediaDevices.getDisplayMedia" in html
    assert "terrain3DControls" in html
    assert "adjustCesiumView(control.id)" in html
    assert 'data-testid="journey-shell"' in html
    assert 'className="journey-shell-content"' in html
    assert "const [isJourneyExportFullscreenLayout, setIsJourneyExportFullscreenLayout] = useState(false);" in html
    assert "const journeyFullscreenActive = isJourneyFullscreen || isJourneyExportFullscreenLayout;" in html
    assert "setIsJourneyExportFullscreenLayout(true);" in html
    assert "restoreSteps.push(() => setIsJourneyExportFullscreenLayout(false));" in html
    assert 'className={`journey-chat-section glass-panel theme-card p-6 rounded-xl shadow-sm ${journeyFullscreenActive ? \'min-h-0\' : \'\'}' in html
    assert "全屏查看" in html
    assert "退出全屏" in html
    assert "生成图片" in html
    assert "fullscreenChatRestoreRef" not in html
    assert "is-chat-collapsed" in html
    assert ".map-compact-action-button {" in html
    assert "width: 52px;" in html
    assert ".map-bottom-button.is-accent-export {" in html
    assert 'className="h-6 w-6 shrink-0"' in html
    assert 'viewBox="0 0 24 24"' in html
    assert 'absolute bottom-4 right-8 z-[1000] map-floating-controls flex items-center gap-2' in html
    assert 'data-export-ignore="true"' in html
    assert 'label="底图"' in html
    assert "{journeyFullscreenActive && chatOpen ? (" in html
    assert "{(!journeyFullscreenActive || chatOpen) ? (" in html
    assert "const [chatOpen, setChatOpen] = useState(true);" in html
    assert 'className="map-layer-trigger map-bottom-button text-sm inline-flex items-center gap-2 hover:bg-white transition-colors"' in html
    assert 'className={`map-layer-tray ${open ? \'is-open\' : \'\'}' in html
    assert 'className="theme-button-secondary px-3 py-1.5 rounded-lg text-xs text-[var(--color-text-secondary)] disabled:opacity-40"' in html
    assert 'className="theme-button-secondary map-bottom-button map-compact-action-button inline-flex items-center justify-center gap-1.5 py-1.5 text-xs text-[var(--color-text-secondary)]"' in html
    assert "<span>{isJourneyFullscreen ? '退出全屏' : '全屏'}</span>" not in html
    assert "{ id: 'zoom-in', label: '+', title: '放大视角' }" in html
    assert "{ id: 'zoom-out', label: '-', title: '缩小视角' }" in html
    assert "{ id: 'rotate-left', label: '左转', title: '向左旋转' }" not in html
    assert "{ id: 'rotate-right', label: '右转', title: '向右旋转' }" not in html
    assert "{ id: 'tilt-up', label: '抬头', title: '抬高视角' }" not in html
    assert "{ id: 'tilt-down', label: '俯视', title: '压低视角' }" not in html
    assert 'className="terrain-compass"' in html
    assert "adjustCesiumView('rotate-left')" in html
    assert "adjustCesiumView('rotate-right')" in html
    assert "adjustCesiumView('tilt-up')" in html
    assert "adjustCesiumView('tilt-down')" in html
    assert "adjustCesiumView('reset-bearing')" in html
    assert "const buildSelectedPinDataUrl = (color) => {" in html
    assert '<circle cx="15" cy="14.4" r="4.8" fill="none" stroke="${main}" stroke-width="1.9" />' in html
    assert "className = 'selected-point-pin'" in html
    assert "const waitForMs = (ms) => new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms || 0))));" in html
    assert "SCREEN_CAPTURE_UNSUPPORTED" in html
    assert "background: rgba(255, 255, 255, 0.98);" in html
    assert "grid-template-rows: minmax(0, var(--journey-top-pane, 64%)) 10px minmax(0, 1fr);" in html
    assert "const freezeScrollableElementForExport = (element) => {" in html
    assert "restoreSteps.push(freezeScrollableElementForExport(chatListRef.current));" in html
    assert "const [topPanePct, setTopPanePct] = useState(64);" in html
    assert "ref={shellContentRef}" in html
    assert "const canvas = await captureCurrentTabFrame();" in html
    assert "link.download = `${safePersonName}-当前视图截图.png`;" in html
    assert ".story-marker-dot {\n  display: none;\n}" in html
    assert ".map-point-core.is-index-only {" in html
    assert "if (shouldShowIndex) div.classList.add('is-index-only');" in html
    assert "strokeWeight: shouldShowIndex ? 0 : 3," in html
    assert "fillOpacity: shouldShowIndex ? 0.14 : 0.35," in html
    assert "'visibility': initialShowIndex ? 'none' : 'visible'" in html
    assert "'circle-stroke-opacity': initialShowIndex ? 0 : 1.0," in html
    assert "map.setLayoutProperty(pointHaloId, 'visibility', shouldShow ? 'none' : 'visible');" in html
    assert "map.setPaintProperty(pointCoreId, 'circle-stroke-opacity', shouldShow ? 0 : 1.0);" in html
    assert "entry.entity.point.pixelSize = shouldShowIndex ? 0 : (isActive ? 18 : (entry.isEndpoint ? 14 : 11));" in html
    assert ".journey-map-column {" in html
    assert ".journey-timeline-column {" in html
    assert ".journey-pane-resizer.is-horizontal" in html
    assert ".journey-pane-resizer.is-vertical" in html

def test_profile_page_template_contains_2d_map_control_hooks():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const map2DControls = [" in html
    assert "{ id: 'fit-all', label: '总览', title: '查看完整轨迹' }" in html
    assert "const adjust2DMapView = (action) => {" in html
    assert "controller.fitAll();" in html
    assert "adjust2DMapView(control.id)" in html
    assert 'label="底图"' in html
    assert "map-layer-switch" in html
    assert "map-layer-card-preview ${opt.previewClass || ''}" in html
    assert "previewClass: 'is-vector'" in html
    assert "previewClass: 'is-imagery'" in html
    assert "previewClass: 'is-terrain'" in html
    assert "previewClass: 'is-terrain3d'" in html
    assert "map-bottom-button map-compact-action-button" in html
    assert "map-control-stack" in html
    assert "map-control-button" in html
    assert "map-2d-control-button" in html
    assert "const getRenderedLngLat = (idx) => {" in html
    assert "const buildRenderedSegmentPath = (idx) => {" in html
    assert "const buildLabelCollisionBox = (screenPoint, detailLevel) => {" in html
    assert "const isLabelCollision = (a, b) => {" in html
    assert "const getPreferredLabelIndexes = ({ activeIdx, detailLevel = 6, isVisible, projectToScreen }) => {" in html
    assert "const getMapPointLabelText = (loc, idx) => {" in html
    assert "const getMapPointLabelVisualState = (loc, idx, activeIdx) => {" in html
    assert "const updateAmapLabelVisibility = (activeIdx) => {" in html
    assert "const updateMapLibreLabelVisibility = (activeIdx) => {" in html
    assert "const updateCesiumLabelVisibility = (activeIdx) => {" in html
    assert "projectToScreen: (lng, lat) => {" in html
    assert "const buildMapPointLabelShell = (loc, idx, activeIdx) => {" in html
    assert "shell.setAttribute('data-story-idx', String(idx));" in html
    assert "const setMapPointLabelMarkerVisibility = (marker, shouldShow) => {" in html
    assert "element: buildMapPointLabelShell(loc, idx, activeIndexRef.current)," in html
    assert "rootEl.classList.contains('map-point-label-shell')" in html
    assert "const scheduleMapLibreOverlayRebuild = (reason = 'unknown') => {" in html
    assert "const healMapLibreOverlaysIfMissing = (reason = 'integrity-check') => {" in html
    assert "const ensureFallbackOverlay = () => {" in html
    assert "const scheduleFallbackOverlayRender = (reason = 'map-change') => {" in html
    assert ".map-fallback-overlay {" in html
    assert "map.on('styledata', () => healMapLibreOverlaysIfMissing('styledata'))" in html
    assert "map.on('idle', () => healMapLibreOverlaysIfMissing('idle'))" not in html
    assert "rebuildOverlaysRef.current();" in html
    assert "{ id: 'vector', label: '矢量', title: '切换到矢量地图', badge: '标准', previewClass: 'is-vector' }" in html
    assert "{ id: 'imagery', label: '影像', title: '切换到卫星影像', badge: '卫星', previewClass: 'is-imagery' }" in html
    assert "{ id: 'terrain', label: '地形', title: '切换到地形图', badge: '地形', previewClass: 'is-terrain' }" in html
    assert "{ id: 'terrain-3d', label: '3D地形', title: '切换到3D地形图', badge: '3D', previewClass: 'is-terrain3d' }" in html
    assert "{ id: 'zoom-in', label: '+', title: '放大地图' }" not in html
    assert "{ id: 'zoom-out', label: '-', title: '缩小地图' }" not in html
    assert "{ id: 'reset', label: '复位', title: '回到当前足迹' }" not in html
    assert "if (action === 'reset') {" not in html
    assert "absolute bottom-4 right-8" in html
    assert "absolute bottom-full right-0 mb-2" not in html
    assert "const getOverviewPadding = (containerWidth) => {" in html
    assert "const getFocusPadding = (containerWidth) => {" in html
    assert "const getAmapBoundsPadding = (containerWidth) => {" in html
    assert "const getAmapFocusPadding = (containerWidth) => {" in html
    assert "const getMapPointLabelOffset = (idx) => {" in html
    assert "maplibre: [0, isEndpoint ? -24 : -20]," in html
    assert "amap: [0, isEndpoint ? -34 : -28]," in html
    assert "offset: new AMap.Pixel(labelOffset.amap[0], labelOffset.amap[1])," in html
    assert "const amapEl = document.getElementById('map-amap');" in html
    assert "map = new AMap.Map('map-amap', {" in html
    assert '<div id="map-amap" className="map-canvas is-hidden"></div>' in html
    assert "const [mapStatusNotice, setMapStatusNotice] = useState(null);" in html
    assert "const retryPreferredMapProvider = (targetLayerType) => {" in html
    assert "const handleMapNoticeAction = (action) => {" in html
    assert "当前: {describeProviderType(mapStatusNotice.provider)} · {describeLayerType(mapStatusNotice.layerType)}" in html
    assert 'aria-label="关闭底图提示"' in html
    assert "我知道了" in html
    assert '>→</button>\n                  </div>' in html
    assert "related-graph-board" in html
    assert "getRelatedGraphEdgeLabel(node)" not in html
    assert 'className="journey-map-column relative flex-1 min-w-0"' in html
    assert 'className="journey-timeline-column glass-panel theme-card rounded-xl overflow-visible flex flex-col min-w-0"' in html
    assert 'className="flex min-h-full flex-col justify-start gap-3"' in html

def test_load_profile_applies_sunbin_summary_and_work_summary_overrides():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "孙膑.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)
    work_summary = (profile.get("workSummaries") or {}).get("孙膑兵法") or {}

    assert "桂陵" in str(profile["person"].get("shortReview") or "")
    assert profile["person"]["highlights"]["works"] == ["孙膑兵法"]
    assert "summary”" not in str(work_summary.get("summary") or "")
    assert "银雀山汉墓竹简" in str(work_summary.get("quote") or "")

def test_load_profile_applies_caiwenji_work_and_achievement_overrides():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "蔡文姬.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)
    work_summary = (profile.get("workSummaries") or {}).get("悲愤诗") or {}

    assert profile["person"]["highlights"]["works"] == ["悲愤诗"]
    assert "作者归属存疑" in str(profile["person"]["highlights"].get("achievements") or "")
    assert "胡笳十八拍" not in str(work_summary.get("quote") or "")
def test_profile_page_template_prefers_geovis_without_vector_probe_preflight():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "await ((window.__MAP_STORY_GEOVIS__ && window.__MAP_STORY_GEOVIS__.ensureMapLibre) || _ensureMapLibre)();" in html
    assert "const scheduleMapLoadFallback = (delayMs) => {" in html
    assert "scheduleMapLoadFallback(12000);" in html
    assert "scheduleMapLoadFallback(18000);" in html
    assert "timeoutMs: 4500" not in html
    assert "probeGeoVisLayerType(geovis, 'vector')" not in html
    assert "if (mode === 'vector') {" in html
    assert "fallbackToMapLibreMode(`${label} 暂不可用，已保留当前 GeoVis 底图。`, mapLayerType);" in html
    assert "title: '已切换到高德备用底图'" in html
    assert "label: '恢复 GeoVis'" in html
    assert "label: `重试${describeLayerType(attemptedLayerType)}`" in html

def test_profile_page_template_removes_embedded_localhost_debug_fetches():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'fetch("http://127.0.0.1:7777/event"' not in html
def test_profile_page_template_uses_colon_for_ancient_and_modern_place_names():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "{loc.ancientName} : {loc.modernName}" in html
    assert "{loc.ancientName} → {loc.modernName}" not in html


def test_profile_page_template_shows_location_resolution_note():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const getLocationResolutionNote = (loc) =>" in html
    assert "geocodeAliasChain" in html
    assert "定位可信度：中高" in html


def test_profile_page_chat_hides_incomplete_group_speaker_marker():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const isIncompleteSpeakerMarker = (text) => /^【[^】]*$/.test" in html
    assert "const isSpeakerMarkerOnly = (text) => /^【[^】]+】$/.test" in html
    assert "if (!text || isIncompleteSpeakerMarker(text) || isSpeakerMarkerOnly(text)) return [];" in html


def test_profile_page_chat_avatar_does_not_overlay_surname_on_image():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const showChatAvatarImage = Boolean(headerAvatarSrc && headerAvatarState !== 'fallback');" in html
    assert "{showChatAvatarImage ? (" in html
    assert "<span className=\"theme-primary-text text-xs font-bold leading-none\">{surname}</span>" in html
    assert "absolute inset-0 flex items-center justify-center" not in html

def test_profile_page_template_simplifies_selected_location_popup_header():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const getSelectedLocDisplayName = (loc) => {" in html
    assert '<h3 className="theme-primary-text text-xl font-bold mb-3">{getSelectedLocDisplayName(selectedLoc)}</h3>' in html
    assert '<span className="font-bold truncate" style={{ fontSize: `${Math.round(14 * timelineZoom)}px` }}>{getSelectedLocDisplayName(loc)}</span>' in html
    assert ".theme-float-section {" in html
    assert ".theme-float-section-title {" in html
    assert ".theme-float-section-body {" in html
    assert 'className="theme-float-section"' in html
    assert 'className="theme-float-section is-accent"' in html
    assert 'className="theme-float-list"' in html
    assert '<p className="text-xs text-gray-400 mb-3">{selectedLoc.ancientName} → {selectedLoc.modernName}</p>' not in html
    assert '<p className="text-gray-400 text-[10px] uppercase font-bold">公元纪年</p>' not in html
    assert '<p className="text-gray-400 text-[10px] uppercase font-bold">停留时间</p>' not in html
    assert '<p className="text-gray-400 text-[10px] uppercase font-bold">事迹描述</p>' not in html

def test_profile_page_template_work_tooltip_avoids_duplicate_title_and_escapes_panel_clipping():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'className="relative z-0 inline-flex align-baseline"' in html
    assert "maxWidth: 'min(420px, calc(100vw - 2rem))'" in html
    assert "bg-white px-3 py-2 text-xs text-gray-700 shadow-[0_18px_40px_rgba(15,23,42,0.22)]" in html
    assert '<span className="mb-1 block font-semibold text-[#7c2d12]">{fullTitle}</span>' not in html
    assert 'className="journey-timeline-column glass-panel theme-card rounded-xl overflow-visible flex flex-col min-w-0"' in html
    assert 'className="glass-panel theme-card rounded-xl overflow-hidden flex flex-col"' not in html
def test_profile_page_template_removes_chat_llm_explanation_copy():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "优先调用 LLM 进行人物对话；若接口暂不可用，则自动回退到人物档案库回答。" not in html
    assert "const getChatFallbackNotice = (meta, error) => {" in html
    assert "当前对话服务不可达，已切换为人物档案库回答。" in html
    assert "LLM 响应超时，已切换为人物档案库回答。" in html
    assert "LLM 调用失败，已切换为人物档案库回答。" in html
    assert "LLM 响应超时，已切换为人物档案智能回答。" in html
    assert "LLM 调用失败，已切换为人物档案智能回答。" in html
    assert "当前未接通 LLM 接口，已切换为人物档案库回答。" not in html

def test_profile_page_template_supports_h3_chat_markdown():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const heading = t.match(/^(#{1,6})\\s+(.*)$/);" in html


def test_profile_page_chat_uses_dedicated_bounded_renderer_without_work_tooltips():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const CHAT_RENDER_MAX_CHARS = 2400" in html
    assert "const CHAT_RENDER_MAX_LINES = 60" in html
    assert "const CHAT_RENDER_MAX_SEGMENTS = 8" in html
    assert "const renderChatBlock = (text) =>" in html
    assert "return renderChatBlock(normalized);" in html
    assert "const hasSpeakerSegments = /【[^】]{1,20}】/.test(rawText);" in html
    assert "if (!hasSpeakerSegments)" in html
    assert "const safeSegments = segments.length ? segments : [{ speaker: '', content: rawText }];" in html
    assert "safeSegments.map((seg, si)" in html
    assert "chat-avatar-partner" in html
    assert "border-l-[3px] border-l-[var(--color-accent)]" in html
    assert "renderChatText(content)" in html
    assert "回答必须简短" in html


def test_profile_page_chat_disables_streaming_and_bounds_context():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "preferStream: false" in html
    assert "if (!preferStream)" in html
    assert ".slice(-6)" in html
    assert ".slice(0, 1200)" in html
    assert "chatRequestTimedOut = true" not in html
    assert "}, 12000)" not in html


def test_profile_page_chat_storage_is_bounded():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".slice(-30)" in html
    assert ".slice(0, 4000)" in html
    assert "String(saved).length > 200000" in html
    assert "window.localStorage.removeItem(chatStorageKey)" in html
    assert "params.get('clear_chat') === '1'" in html


def test_profile_page_template_removes_floating_chat_button_and_keeps_inline_entry():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "打开对话" in html
    assert "收起对话" in html
    assert "aria-label={chatOpen ? '收起对话' : '打开对话'}" in html
    assert "fixed bottom-6 right-6" not in html
    assert "`跟${data.person.name}对话`" not in html
    assert ">NEW</span>" not in html

def test_profile_page_template_uses_recommended_question_cards_and_plain_teaching_points():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "推荐问题" in html
    assert "推荐任务" not in html
    assert "const profileScores = {" in html
    assert "const rankedProfiles = Object.entries(profileScores)" in html
    assert "addScore('ruler', 6, /(皇帝|帝王|国王|女王|君主|王朝|王室|可汗|汗王|摄政|登基|加冕|称帝|即位|统治者|皇后|王后)/, rolePool);" in html
    assert "addScore('military', 6, /(将军|将领|统帅|武将|元帅|领兵|统军|用兵|征服者|军旅|军功)/, rolePool);" in html
    assert "(将军|将领|统帅|军|侯|王|征战|战役|战场|兵|骑|伐|守边|武将)" not in html
    assert "push('帝国治理'" in html
    assert "push('权力来源'" in html
    assert "push('写作缘起'" in html
    assert "recommended-question-grid" in html
    assert "recommended-question-card" in html
    assert "recommended-question-kicker" in html
    assert "teaching-point-heading-inline" in html
    assert "teaching-point-subheading-inline" in html
    assert "teaching-point-line" in html
    assert "teaching-point-inline-bullet" in html
    assert "teaching-point-paragraph" in html
    assert "teaching-point-card" in html
    assert "text-left" in html

def test_profile_page_template_uses_context_aware_war_badge_rule():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const warPattern = /(战争|战事|战场|交战|作战|参战|战役|会战|抗战|抗敌|起义|兵变|兵败|兵临|攻城|守城|攻伐|讨伐|征讨|征战|交锋)/;" in html
    assert "if (warPattern.test(pool)) push('war', '战争');" in html
    assert "if (/(战|伐|兵|军|攻|守|起义|征讨|抗战|会战|战役|交锋)/.test(pool)) push('war', '战争');" not in html

def test_profile_page_template_uses_precise_travel_badge_rule():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const travelPattern = /(游历|巡游|巡幸|迁居|迁徙|迁往|迁至|迁到|出使|远行|远赴|流放|流寓|谪居|谪迁|赴任|奔赴|抵达|定居|南下|北上|东行|西行|启程)/;" in html
    assert "if (travelPattern.test(pool)) push('travel', '行旅');" in html
    assert "if (/(游|行|巡|迁|至|出使|远行|流放|谪|入朝|赴|抵达|定居)/.test(pool)) push('travel', '行旅');" not in html

def test_profile_page_template_uses_precise_politics_badge_rule():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const politicsPattern = /(任官|出任|主政|执政|从政|辅政|摄政|拜相|为相|宰相|丞相|尚书|刺史|太守|封侯|封王|称王|称帝|即位|登基|改革|变法|新政)/;" in html
    assert "const hasPolitics = politicsPattern.test(pool);" in html
    assert "if (hasPolitics) push('politics', '仕途');" in html
    assert "if (/(任|官|相|帝|王|后|宰相|执政|改革|变法|称帝|即位|登基|拜相)/.test(pool)) push('politics', '仕途');" not in html

def test_profile_page_template_avoids_repeated_map_reactivation_on_ready_tick():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "}, [mapLayerType, mapRecoveryTick]);" in html
    assert "}, [mapLayerType, mapReadyTick]);" not in html
    assert "[0, 120, 320, 700].forEach((delay) => {" not in html
    assert "[180, 900, 2200].forEach((delay) => {" not in html

def test_profile_page_template_keeps_active_index_ref_synced_across_map_click_paths():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "activeIndexRef.current = 0;" in html
    assert html.count("activeIndexRef.current = idx;") >= 3
    assert "mapRef.current.pulse(activeIndex);" not in html

def test_profile_page_template_uses_maplibre_circle_layers_for_story_points():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const pointSourceId = 'story-point-source';" in html
    assert "const pointHaloId = 'story-point-halo';" in html
    assert "const pointCoreId = 'story-point-core';" in html
    assert "type: 'circle'" in html
    assert "map.on('click', pointCoreId, onPointLayerClick)" in html
    assert "if (!loc) return null;" in html
    assert "idx === 0 || idx === total - 1) return null" not in html
    assert "endpointLayer:" not in html
    assert "buildMapPointLabelElement" in html
    assert "updateMapPointLabelElement" in html
    assert "new maplibregl.Marker({" in html

def test_profile_page_template_restores_maplibre_pulse_marker_feedback():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const runPulse = (lng, lat, color) => {" in html
    # The pulse className is now set inside acquirePulseElement (pool); the
    # literal assignment string may appear in either helper.
    assert ("el.className = 'map-pulse-marker';" in html
            or "fresh.className = 'map-pulse-marker';" in html)
    assert "new maplibregl.Marker({" in html
    assert ".setLngLat([Number(lng), Number(lat)])" in html
    assert "const renderLoc = getRenderedPointLoc(idx);" in html
    assert "const pulseLng = Number.isFinite(Number(renderLoc?.renderLng)) ? Number(renderLoc.renderLng) : Number(loc.lng);" in html
    assert "const pulseLat = Number.isFinite(Number(renderLoc?.renderLat)) ? Number(renderLoc.renderLat) : Number(loc.lat);" in html
    assert "const runPulse = (lng, lat, color) => {\n        return;" not in html

def test_profile_page_template_distinguishes_terrain_palette_and_uniform_line_width():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const getTerrainContrastPalette = (segmentColor, segmentIdx, layerType) => {" in html
    assert "if (layerType === 'terrain-3d')" in html
    assert "const uniformLineWidth = layerType === 'terrain-3d' ? 11.6 : (isContrastMode ? 6.4 : 5.6);" in html
    assert "viewer.camera.setView({" in html
    assert "viewer.camera.changed.addEventListener(() => {" in html
    assert "baseColor: mixHex(base, accent, 0.78)," in html
    assert "const uniformHaloWidth = layerType === 'terrain-3d' ? 24.5 : (isContrastMode ? 18.5 : 15.5);" in html
    assert "glowPower: segmentVisual.isCurrent ? 0.4 : 0.3" in html
    assert "const buildCesiumSegmentHaloMaterial = (segmentVisual) => (" in html
    assert "width: initialVisual.haloLineWidth + 2.4," in html
    assert html.count("showArrow: false,") >= 2
    assert "controller.fitAll(false);" in html
    assert "heading: 0," in html
    assert "Math.max(sphere.radius * 5.2, 1100000)" in html
    assert "if (hasLocHash()) {" in html
    assert "focusIndex(activeIndexRef.current, false);" in html

def test_profile_page_template_skips_initial_hash_write_for_default_overview():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const skippedInitialHashWriteRef = useRef(false);" in html
    assert "if (!skippedInitialHashWriteRef.current && !initialLocFromHash && activeIndex === initialLocIdx) {" in html

def test_profile_page_template_defaults_to_overview_while_showing_first_location_details():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const [selectedLoc, setSelectedLoc] = useState(locations[initialLocIdx] || null);" in html
    assert "const skippedInitialOverviewActiveSyncRef = useRef(false);" in html
    assert "if (hasLocHash()) {" in html
    assert "applyFitBounds();" in html
    assert "controller.fitAll(false);" in html
    assert "setActive(activeIndexRef.current);" in html
    assert "if (!initialLocFromHash && activeIndex === initialLocIdx && !skippedInitialOverviewActiveSyncRef.current) {" in html

def test_profile_page_template_does_not_resync_active_marker_on_every_segment_tick():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const refreshAnimatedSegmentFrame = React.useCallback(() => {" in html
    assert "try { controller.followSegmentProgress(state.segmentIdx, state.progress); } catch (_) {}" in html
    assert "try { controller.setActive(activeIndexRef.current); } catch (_) {}" not in html

def test_profile_page_template_does_not_rebuild_maplibre_overlays_from_idle_events():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "try { map.on('styledata', () => healMapLibreOverlaysIfMissing('styledata')); } catch (_) {}" in html
    assert "try { map.on('idle', () => healMapLibreOverlaysIfMissing('idle')); } catch (_) {}" not in html

def test_profile_page_template_clears_fallback_overlay_at_drag_start_and_only_restores_when_needed():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const scheduleFallbackOverlayRender = (reason = 'map-change') => {" in html
    assert "try { map.on('movestart', () => {" in html
    assert "try { map.on('zoomstart', () => {" in html
    assert "try { map.on('moveend', () => {" in html
    assert "const missingArtifacts = !hasRenderableOverlayArtifacts();" in html
    assert "if (missingArtifacts) scheduleFallbackOverlayRender('moveend');" in html
    assert "try { map.on('zoomend', () => {" in html
    assert "if (missingArtifacts) scheduleFallbackOverlayRender('zoomend');" in html

def test_profile_page_template_rebinds_existing_amap_controller_when_reentering_fallback():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const reusingExistingMap = Boolean(map);" in html
    assert "if (reusingExistingMap && amapControllerRef.current) {" in html
    assert "mapRef.current = amapControllerRef.current;" in html
    assert "setMapLoadState('ready');" in html

def test_profile_page_template_shows_age_and_city_name_on_map_node_labels():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const getMapPointLabelName = (loc, idx) => (" in html
    assert "const buildMapPointLabelElement = (loc, idx, activeIdx) => {" in html
    assert "return badgeText && name ? `${badgeText}\\n${name}` : (badgeText || name);" in html
    assert "const getMapPointLabelText = (loc, idx) => {" in html
    assert "const buildMapPointLabelShell = (loc, idx, activeIdx) => {" in html
    assert "element: buildMapPointLabelShell(loc, idx, activeIndexRef.current)," in html
    assert "setMapPointLabelMarkerVisibility(marker, shouldShow);" in html
    assert "const getRenderedPointLoc = (idx) => {" in html

def test_profile_page_template_highlights_active_map_point_numbers_without_filled_center():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "indexBadgeRadius: visual.radius + (visual.isActive ? 4.8 : 3.8)," in html
    assert "indexBadgeStrokeColor: visual.isActive ? hexToRgba(pointColor, 0.4) : 'rgba(148,163,184,0.28)'" in html
    assert "indexTextColor: visual.isActive ? pointColor : '#0f172a'" in html
    assert "indexTextHaloWidth: visual.isActive ? 1.8 : 1.4," in html
    assert "'visibility': initialShowIndex ? 'visible' : 'none'" in html
    assert "map.setLayoutProperty(pointRingOuterId, 'visibility', 'none');" in html
    assert "'text-color': ['get', 'indexTextColor']" in html
    assert "color: isActive ? pointColor : '#0f172a'," in html
    assert "fontSize: isActive ? '14px' : '13px'," in html
    assert 'class="map-point-label-text"' in html
    assert 'class="map-point-label-badge"' in html
    assert 'class="map-point-label-name"' in html
    assert "font-size: 11px;" in html
    assert "maplibre: [0, isEndpoint ? -24 : -20]," in html
    assert "amap: [0, isEndpoint ? -34 : -28]," in html

def test_profile_page_template_includes_person_specific_recommended_questions():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const customPromptMap = {" in html
    assert "'诸葛亮': [" in html
    assert "question: '你为什么写《出师表》？'" in html
    assert "'刘禅': [" in html
    assert "question: '你怎么看《出师表》？'" in html
    assert "'鲁迅': [" in html
    assert "question: '你怎么看瓜田里的猹？'" in html
    assert "'牛顿': [" in html
    assert "question: '那颗苹果怎么砸醒你的？'" in html
    assert "'曹操': [" in html
    assert "question: '你当时为何杀吕伯奢一家？'" in html
    assert "(customPromptMap[personName] || []).forEach((item) => {" in html

def test_profile_page_template_does_not_fake_zero_age_for_unknown_start_age():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const ageText = getAgeText(loc) || (idx === 0 ? '年龄待考' : (idx === totalEvents - 1 ? '终章' : '年龄待考'));" in html
    assert "return ageText || '0岁';" not in html

def test_profile_page_template_uses_high_contrast_amap_text_label_style():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const buildAmapPointLabelStyle = (visual) => ({" in html
    assert "color: visual.textColor," in html
    assert "textShadow: visual.isActive ? '0 1px 0 rgba(255,255,255,0.92)' : '0 1px 0 rgba(255,255,255,0.86)'" in html
    assert "style: buildAmapPointLabelStyle(visual)" in html
    assert "entry.label.setStyle(buildAmapPointLabelStyle(visual));" in html
    assert "color: pointColor," not in html
