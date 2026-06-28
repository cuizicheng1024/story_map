import importlib
import sys
import typing


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

TEMPLATE_PATH = REPO_ROOT / "storymap" / "script" / "profile" / "templates" / "profile_page.html"

from storymap.script.cli import story_map
from storymap.script.core.artifacts import _extract_export_data_from_html
from storymap.script.profile import builder as profile_builder
from storymap.script.profile import renderer
from storymap.script.profile.renderer import render_profile_html


def test_render_profile_html_uses_external_template():
    html = render_profile_html(
        {
            "person": {"name": "测试人物", "description": "生平简介"},
            "locations": [],
            "highlights": {},
        }
    )

    assert "__TITLE__" not in html
    assert "__DATA__" not in html
    assert "测试人物的人生足迹地图" in html
    assert '<link rel="icon" type="image/png" sizes="32x32" href="./orange.png?v=20260617-tab" />' in html
    assert '<link rel="shortcut icon" href="./orange.png?v=20260617-tab" />' in html
    assert '<link rel="apple-touch-icon" href="./orange.png?v=20260617-tab" />' in html
    assert "window.__EXPORT_DATA__ = data;" in html
    assert "personName: String(data?.person?.name || '').trim()" in html
    payload = _extract_export_data_from_html(html)
    assert payload["personRedirects"].get("苏东坡") == "苏轼"
    assert payload["templateSignature"] == renderer.profile_template_signature()


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


def test_render_profile_html_includes_streaming_history_chat_client_logic():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "stream: true," in html
    assert "const reader = resp.body.getReader();" in html
    assert "onDelta" in html and "fullText" in html
    assert "const chatAbortControllerRef = useRef(null);" in html
    assert "const chatFlushTimerRef = useRef(null);" in html
    assert "const chatDisplayQueueRef = useRef([]);" in html
    assert "const chatDisplayedTextRef = useRef('');" in html
    assert "splitStreamDeltaForDisplay" in html
    assert "pumpStreamedChatDisplay" in html
    assert "signal," in html
    assert "abortCurrentChatRequest();" in html
    assert "}, 24);" in html
    assert "controller && controller.signal && controller.signal.aborted" in html


def test_render_profile_html_falls_back_to_runtime_babel_when_precompile_is_unavailable(monkeypatch):
    renderer._compiled_profile_template.cache_clear()
    renderer._compiled_profile_app_js.cache_clear()
    monkeypatch.setattr(renderer, "_compiled_profile_app_js", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert '<script src="./vendor/babel.min.js"></script>' in html
    assert '<script type="text/babel"' in html
    assert "window.__EXPORT_DATA__ = data;" in html
    renderer._compiled_profile_template.cache_clear()


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


def test_render_profile_html_injects_shared_person_tooltip_helper():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "__PERSON_TOOLTIP_JS__" not in html
    assert "const buildPersonTooltipModel = (node, options = {}) => {" in html
    assert "const uniqStrings = items => {" in html
    assert "const tipModel = buildPersonTooltipModel(node, {" in html
    assert "fallbackName: '相关人物'" in html
    assert "tipModel.rows.map(row => React.createElement(" in html


def test_render_profile_html_prefers_foreign_name_as_primary_header():
    html = render_profile_html(
        {
            "person": {"name": "乔纳森·斯威夫特", "foreignName": "Jonathan Swift"},
            "locations": [],
            "highlights": {},
        }
    )

    assert "const personForeignName = String(data.person?.foreignName || data.person?.foreign_name || '').trim();" in html
    assert "const headerPrimaryName = personForeignName || String(data.person?.name || '').trim();" in html
    assert "tipModel.displayName || tipModel.name" in html
    assert "secondaryName" in html
    assert "related-graph-tooltip-row" in html


def test_timeline_card_click_uses_strict_map_focus():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})
    template_source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const normalizeFocusOptions = raw => {" in html
    assert "controller.focusIndex(idx, {" in html
    assert "pulse: pulseNow" in html
    assert "strict" in html
    assert "const run = (pulseNow = pulse, syncActive = true) => {" in html
    assert "if (syncActive && typeof idx === 'number' && typeof controller.setActive === 'function') {" in html
    assert "try { run(false, false); } catch (_) {}" in template_source
    assert "applySelectionToMap(idx, loc, {" in html
    assert "stabilize: true" in html


def test_profile_template_throttles_maplibre_overlay_rebuild_feedback_loop():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "let overlayRebuildInProgress = false;" in html
    assert "let overlayRebuildMutedUntil = 0;" in html
    assert "const performOverlayRebuild = (reason = 'unknown') => {" in html
    assert "if (overlayRebuildInProgress) return false;" in html
    assert "if (now < overlayRebuildMutedUntil) return false;" in html
    assert "overlayRebuildMutedUntil = Date.now() + 320;" in html


def test_profile_template_declares_curved_segment_builder_before_usage():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "function buildCurvedSegmentPath(from, to, idx, prev, next) {" in html
    assert "function getSegmentDistanceKm(from, to) {" in html
    assert "function getApproximateContinent(coord) {" in html
    assert "function shouldSkipSegmentConnection(from, to, rawContext) {" in html
    assert "shouldSkipSegmentConnection(" in html
    assert "buildFlowDotHtml" not in html
    assert "showFlowDots" not in html
    assert html.index("function buildCurvedSegmentPath(from, to, idx, prev, next) {") < html.index("const buildRenderedSegmentPath = idx => {")


def test_profile_template_marks_posthumous_events_instead_of_fake_age():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const compact = raw.replace(/\\s+/g, '');" in html
    assert "const match = compact.match(/((?:约|大约|约莫|约公元前|公元前|前)?)(\\d{1,4})年/);" in html
    assert "const deathYear = useMemo(() => extractYear(deathDate), [deathDate]);" in html
    assert "if (deathYear && year > deathYear) return null;" in html
    assert "if (isPosthumousEvent(loc)) return '身后';" in html
    assert "if (loc.type === 'birth' || idx === 0) return ageText || '年龄待考';" in html
    assert "return badgeText && name ? `${badgeText}\\n${name}` : badgeText || name;" in html
    assert 'class="map-point-label-badge"' in html
    assert 'class="map-point-label-name"' in html


def test_profile_template_defines_birthplace_label_before_intro_tags_use_it():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    birthplace_idx = html.index("const birthplaceLabel = useMemo(() => {")
    intro_tags_idx = html.index("const introTags = useMemo(() => {")

    assert birthplace_idx < intro_tags_idx
    assert "const birthplaceDisplayLabel = useMemo(() => {" in html
    assert "if (birthplaceDisplayLabel) push(`出生地：${birthplaceDisplayLabel}`);" in html
    assert "const showNativePlaceLabel = useMemo(() => {" in html
    assert "if (showNativePlaceLabel) push(`籍贯：${nativePlaceLabel}`);" in html


def test_profile_template_defines_journey_panel_sizes_before_effect_uses_them():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    panel_height_idx = html.index("const journeyPanelHeight = journeyFullscreenActive")
    sync_effect_idx = html.index("const syncMapViewport = () => {")

    assert panel_height_idx < sync_effect_idx
    assert "mapEl.style.height = journeyPanelHeight;" in html
    assert "mapEl.style.minHeight = journeyPanelMinHeight;" in html
    assert ": 'clamp(480px, 68vh, 760px)';" in html
    assert "const journeyPanelMinHeight = journeyFullscreenActive ? '0px' : '480px';" in html


def test_profile_template_uses_natural_ambiguous_birthplace_note_copy():
    template_source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "出生地说法：" in template_source


def test_profile_template_persists_stage_key_point_labels_and_shows_all_segment_arrows():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const getPersistentLabelIndexes = () => {" in html
    assert "const stageRatios = total >= 10 ? [0.2, 0.4, 0.6, 0.8] : [0.25, 0.5, 0.75];" in html
    assert "const essential = getPersistentLabelIndexes();" in html
    assert "const stride = totalSegments >= 12 ? 3 : totalSegments >= 7 ? 2 : 1;" in html
    assert "if (item.distance >= 80 && order % stride === 0) keep.add(item.idx);" in html
    assert "showArrow: false," in html


def test_profile_template_zooms_out_single_point_story_to_show_basemap():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const defaultFocusZoom = locations.length <= 1 ? 5.6 : 10;" in html
    assert "const v = Number.isFinite(z) ? z : defaultFocusZoom;" in html
    assert "if (boundsPoints.length === 1) {" in html
    assert "map.easeTo({" in html
    assert "center: boundsPoints[0]" in html
    assert "zoom: focusZoom" in html


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


def test_runtime_map_config_loaders_prefer_same_origin_before_runtime_api_base():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "window.__MAP_STORY_RUNTIME_CONFIG_CANDIDATES__" in html
    # Same-origin branch now also gates on isDevHost so static prod
    # (file://) skips it while localhost dev can still resolve.
    assert "window.location.protocol !== 'file:' && isDevHost" in html
    assert "push(new URL(`./${String(filename || '').replace(/^\\/+/, '')}`, window.location.href).toString());" in html
    assert "const apiBase = String(window.MAP_STORY_API_BASE || '').trim();" in html
    assert "push(apiBase.replace(/\\/+$/, '') + '/' + String(filename || '').replace(/^\\/+/, ''));" in html
    assert html.index("push(new URL(`./${String(filename || '').replace(/^\\/+/, '')}`, window.location.href).toString());") < html.index(
        "push(apiBase.replace(/\\/+$/, '') + '/' + String(filename || '').replace(/^\\/+/, ''));"
    )


def test_static_profile_page_tries_local_ai_proxy_on_localhost():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "if ((!staticSite || isLocalHost) && window.location && window.location.protocol !== 'file:') {" in html
    assert "pushUrl(new URL('./api/ai/proxy', window.location.href).toString());" in html
    assert "if (!staticSite || isLocalHost) {" in html
    assert "pushUrl('http://127.0.0.1:8765/api/ai/proxy');" in html
    assert html.index("pushUrl(new URL('./api/ai/proxy', window.location.href).toString());") < html.index(
        "pushUrl('http://127.0.0.1:8765/api/ai/proxy');"
    )


def test_chat_fallback_notice_hides_raw_failed_to_fetch_message():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const _isChatEndpointUnavailableError = error => {" in html
    assert "'failed to fetch'" in html
    assert "throw _normalizeChatRequestError(lastErr || new Error('LLM_ENDPOINT_UNAVAILABLE'));" in html
    assert "if (!message || _isChatEndpointUnavailableError(error)) {" in html


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

    assert 'rel="preload" href="./vendor/tailwindcss.js" as="script"' in html
    assert 'rel="preload" href="./vendor/react.production.min.js" as="script"' in html
    assert 'rel="preload" href="./vendor/react-dom.production.min.js" as="script"' in html
    assert 'rel="preload" href="./vendor/babel.min.js" as="script"' in html
    # Sanity: preloads come before the actual script tags
    preload_pos = html.index('rel="preload" href="./vendor/tailwindcss.js"')
    script_pos = html.index('<script src="./vendor/tailwindcss.js"></script>')
    assert preload_pos < script_pos


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


def test_loading_state_uses_skeleton_shimmer():
    """UX3: when the map is loading, the lazy-card title must use a
    skeleton placeholder so the user perceives forward motion."""

    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".map-lazy-title.is-skeleton" in html
    assert "@keyframes map-lazy-shimmer" in html
    assert "is-skeleton' : ''}" in html


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


def test_map_html_renderer_type_hints_resolve_for_canonical_person_name():
    registry = importlib.import_module("storymap.script.core.person_registry")
    hints = typing.get_type_hints(registry.canonical_person_name)

    assert "available_names" in hints
    assert hints["return"] is str


def test_related_people_graph_dedupes_real_story_alias_pages(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    payload = {
        "nodes": [
            {
                "person": "王安石",
                "file": "王安石.html",
                "dynasty": "北宋",
                "birth_year": 1021,
                "death_year": 1086,
                "domain_tags": ["文学"],
            },
            {
                "person": "苏轼",
                "file": "苏轼.html",
                "dynasty": "北宋",
                "birth_year": 1037,
                "death_year": 1101,
                "domain_tags": ["文学"],
            },
            {
                "person": "苏东坡",
                "file": "苏东坡.html",
                "dynasty": "北宋",
                "birth_year": 1037,
                "death_year": 1101,
                "domain_tags": ["文学"],
            },
        ],
        "edges": [
            {"a": 0, "b": 1, "type": "manual", "label": "政坛交游", "confidence": 0.9, "weight": 3},
            {"a": 0, "b": 2, "type": "manual", "label": "别名关系", "confidence": 0.9, "weight": 3},
        ],
    }
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: payload)

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "王安石", "dynasty": "北宋"},
            "markdown": "# 王安石\n\n王安石与苏轼同朝。",
        }
    )

    names = [str(node.get("name") or "") for node in (related.get("nodes") or [])]
    assert names.count("苏轼") == 1
    assert names.count("苏东坡") == 0


def test_related_people_graph_preserves_raw_alias_display_for_foreign_names(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    payload = {
        "nodes": [
            {
                "person": "玛丽亚·斯克沃多夫斯卡·居里",
                "file": "玛丽·居里.html",
                "aliases": ["玛丽·居里"],
                "dynasty": "19世纪末至20世纪初",
            }
        ],
        "edges": [],
    }
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: payload)

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "玛丽·居里", "dynasty": "19世纪末至20世纪初"},
            "markdown": "# 玛丽·居里\n\n居里夫人是放射性研究先驱。",
        }
    )

    center = related.get("center") or {}
    aliases = center.get("aliases") or []
    assert "玛丽居里" not in aliases
    assert "玛丽亚·斯克沃多夫斯卡·居里" in aliases


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


def test_related_people_graph_handles_sparse_raw_node_indexes(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    payload = {
        "nodes": [
            {
                "person": "王安石",
                "file": "王安石.html",
                "dynasty": "北宋",
            },
            "invalid-node",
            {
                "person": "苏轼",
                "file": "苏轼.html",
                "dynasty": "北宋",
            },
            {
                "person": "曾巩",
                "file": "曾巩.html",
                "dynasty": "北宋",
            },
        ],
        "edges": [
            {"a": 0, "b": 2, "type": "manual", "label": "政坛交游", "confidence": 0.9, "weight": 3},
        ],
    }
    monkeypatch.setattr(renderer, "_load_stellar_home_data", lambda: payload)

    related = renderer._build_related_people_graph(
        {
            "person": {"name": "王安石", "dynasty": "北宋"},
            "markdown": "# 王安石\n\n王安石与苏轼同朝。",
        }
    )

    names = [str(node.get("name") or "") for node in (related.get("nodes") or [])]
    links = related.get("links") or []
    assert "苏轼" in names
    assert any(
        str(link.get("target") or "") == "苏轼" and str(link.get("label") or "") == "政坛交游"
        for link in links
    )


def test_load_profile_prefers_work_quote_for_literary_person():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李斯.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "泰山不让土壤" in str(profile["person"].get("quote") or "")
    assert "泰山不让土壤" in str(profile["person"].get("shortReview") or "")


def test_load_profile_prefers_explicit_summary_short_review_over_spotlight_fallback():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李白.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "天才英特" in str(profile["person"].get("shortReview") or "")


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


def test_render_profile_html_limits_teaching_review_subtitle_to_short_lines():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const extractTeachingReviewSubtitle = raw => {" in html
    assert "const splitRe = new RegExp(`${CR}${LF}|${CR}|${LF}|${BS}${BS}n`, 'g');" in html
    assert "if (t.length > 80) return true;" in html


def test_render_profile_html_prefers_short_review_and_work_hover_helpers():
    html = render_profile_html({"person": {"name": "测试人物", "shortReview": "短评"}, "locations": [], "highlights": {}})

    assert "const shortReview = String(data.person?.shortReview || data.person?.quote || '').trim();" in html
    assert "const WorkTitleWithTooltip = ({" in html
    assert "const renderWorkTitleWithTooltip = (fullTitle, key, className) => React.createElement(WorkTitleWithTooltip" in html
    assert 'className: className || "work-title-link"' in html
    assert ".work-title-link {" in html
    assert "quotePolicy: String(item.quote_policy || '').trim()" in html
    assert "quotePolicy === 'summary_only' && !quoteItems.length" in html


def test_render_profile_html_prefers_shared_work_tooltips_before_local_and_fallback():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const SHARED_WORK_TOOLTIP_TEXTS = {" in html
    assert "'隆中对': '“天下有变，则命一上将将荆州之军以向宛、洛，将军身率益州之众出于秦川。”\\n“诚如是，则霸业可成，汉室可兴矣。”'" in html
    assert "'出师表': '“鞠躬尽瘁，死而后已。”'" in html
    assert "'滕王阁序': '“落霞与孤鹜齐飞，秋水共长天一色。”'" in html
    assert "'岳阳楼记': '“先天下之忧而忧，后天下之乐而乐。”'" in html
    assert "'醉翁亭记': '“醉翁之意不在酒，在乎山水之间也。”'" in html
    assert "'桃花源记': '“土地平旷，屋舍俨然，有良田、美池、桑竹之属。”'" in html
    assert "'师说': '“师者，所以传道受业解惑也。”'" in html
    assert "'兰亭集序': '“后之视今，亦犹今之视昔。”'" in html
    assert "'赤壁赋': '“寄蜉蝣于天地，渺沧海之一粟。”'" in html
    assert "'陋室铭': '“斯是陋室，惟吾德馨。”'" in html
    assert "'阿房宫赋': '“灭六国者六国也，非秦也；族秦者秦也，非天下也。”'" in html
    assert "'小石潭记': '“潭中鱼可百许头，皆若空游无所依。”'" in html
    assert "const sharedWorkTextLibrary = buildWorkTooltipLibrary(SHARED_WORK_TOOLTIP_TEXTS);" in html
    assert "const workTextLibrary = buildWorkTooltipLibrary(rawWorkTexts);" in html
    assert "const sharedText = String(sharedWorkTextLibrary[alias] || '').trim();" in html
    assert "const localText = extractWorkOriginalSentence(workTextLibrary[alias] || '');" in html
    assert "const fallbackText = getWorkTooltipFallbackText(title);" in html
    assert html.index("const sharedText = String(sharedWorkTextLibrary[alias] || '').trim();") < html.index("const localText = extractWorkOriginalSentence(workTextLibrary[alias] || '');")
    assert html.index("const localText = extractWorkOriginalSentence(workTextLibrary[alias] || '');") < html.index("const fallbackText = getWorkTooltipFallbackText(title);")


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


def test_related_people_graph_cleans_invalid_center_fields_from_shared_payload(monkeypatch):
    renderer._load_stellar_home_data.cache_clear()
    renderer.invalidate_graph_service_cache()
    payload = {
        "nodes": [
            {
                "person": "孙膑",
                "file": "孙膑.html",
                "dynasty": "战国",
                "time_year": -348,
                "quote": "{",
                "review": "",
                "birthplace": "- **去世**：",
                "birthplace_modern": "",
                "main_role_label": "军事家",
            },
            {
                "person": "田忌",
                "file": "田忌.html",
                "dynasty": "战国",
                "birth_year": -380,
                "death_year": -320,
            },
        ],
        "edges": [{"a": 0, "b": 1, "type": "bio", "label": "君臣", "confidence": 0.88}],
    }
    monkeypatch.setattr(renderer, "get_related_people_graph", lambda person, markdown="", limit=6: {})
    monkeypatch.setattr(renderer, "load_home_graph_payload", lambda _path=None: payload)

    html = render_profile_html(
        {
            "person": {
                "name": "孙膑",
                "dynasty": "战国",
                "quote": "辅佐田忌，策划桂陵、马陵之战。",
                "shortReview": "辅佐田忌，策划桂陵、马陵之战。",
                "birthplace": "",
                "birth": {"date": "", "location": ""},
                "death": {"date": "", "location": ""},
            },
            "locations": [],
            "highlights": {},
            "markdown": "# 孙膑\n\n辅佐田忌，策划桂陵、马陵之战。",
        }
    )

    center = ((_extract_export_data_from_html(html).get("relatedGraph") or {}).get("center") or {})

    assert center.get("birth_year") is None
    assert center.get("birthplace") == ""
    assert center.get("quote") == "辅佐田忌，策划桂陵、马陵之战。"
    assert "draggingRef.current = 'horizontal';" in html
    assert "draggingRef.current = 'vertical';" in html


def test_profile_page_template_boots_map_by_viewport_and_supports_segment_animation():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const [mapLoadState, setMapLoadState] = useState('idle');" in html
    assert "const [mapInitRequestTick, setMapInitRequestTick] = useState(0);" in html
    assert "const requestMapInitialization = React.useCallback((reason = 'manual') => {" in html
    assert "requestMapInitialization('boot');" not in html
    assert "new window.IntersectionObserver((entries) => {" in html
    assert "requestViewportInit('viewport');" in html
    assert "requestViewportInit('fallback');" in html
    assert "正文与时间轴会优先显示；当地图区域进入视口时，再初始化底图、轨迹与地点标注。" in html
    assert "立即展开地图" in html
    assert "journeyFullscreenActive && !chatOpen" in html
    assert "onClick={() => setChatOpen(true)}" in html
    assert "if (typeof geovis.ensureConfig === 'function') {" in html
    assert "await geovis.ensureConfig();" in html
    assert "if (mapInitRequestTick <= 0 || mapRef.current) return () => { disposed = true; };" in html
    assert "data-testid=\"profile-map-lazy-overlay\"" in html
    assert "const mapLazyTitle = mapIdle" in html
    assert "正在初始化底图、轨迹和地点标注，人物正文已经可以正常浏览。" in html
    assert "地图已完成初始化。" in html
    assert "onClick={() => requestMapInitialization('manual')}" in html
    assert "flex min-h-full flex-col justify-start gap-3" in html
    assert "{mapReady ? (" in html
    assert "{mapReady && mapStatusNotice ? (" in html
    assert "function buildPartialSegmentPath(path, progress) {" in html
    assert "function getSegmentFollowCenter(path, progress) {" in html
    assert "const startSegmentTransition = React.useCallback((fromIdx, toIdx) => {" in html
    assert "followSegmentProgress: (segmentIdx, progress) => {" in html


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


def test_renderer_bootstrap_uses_runtime_script_loader_and_api_base_candidates():
    amap_html = renderer._amap_bootstrap_html()
    geovis_html = renderer._profile_map_bootstrap_html()

    assert "window.__MAP_STORY_RUNTIME_CONFIG_CANDIDATES__" in amap_html
    assert "window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__" in amap_html
    assert "window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__" in amap_html
    # The same-origin branch now also gates on isDevHost so static
    # production builds (file://) skip it while localhost dev can still
    # resolve runtime config.
    assert "window.location.protocol !== 'file:' && isDevHost" in amap_html
    assert "push(new URL(`./${String(filename || '').replace(/^\\/+/, '')}`, window.location.href).toString());" in amap_html
    assert "push(apiBase.replace(/\\/+$/, '') + '/' + String(filename || '').replace(/^\\/+/, ''));" in amap_html
    assert amap_html.index("push(new URL(`./${String(filename || '').replace(/^\\/+/, '')}`, window.location.href).toString());") < amap_html.index(
        "push(apiBase.replace(/\\/+$/, '') + '/' + String(filename || '').replace(/^\\/+/, ''));"
    )
    assert "await window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__('amap', 'amap-config.js', () => Boolean(_getAmapKey()));" in amap_html
    assert "cacheKey: 'amap-sdk'" in amap_html
    assert "cacheKey: 'maplibre-sdk'" in geovis_html
    assert "cacheKey: 'cesium-sdk'" in geovis_html
    assert "ensureConfig: () => (" in geovis_html
    assert "window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__('geovis', 'geovis-config.js', () => Boolean(_getGeoVisToken()))" in geovis_html


def test_profile_page_template_uses_colon_for_ancient_and_modern_place_names():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "{loc.ancientName} : {loc.modernName}" in html
    assert "{loc.ancientName} → {loc.modernName}" not in html


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


def test_profile_page_template_simplifies_related_graph_and_merges_su_shi_alias():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const getCanonicalPersonName = (name) => {" in html
    assert "const redirects = data?.personRedirects && typeof data.personRedirects === 'object' ? data.personRedirects : {};" in html
    assert "const getPersonAliasList = (personName, aliases = []) => {" in html
    assert "const RELATED_GRAPH_CENTER_COPY = '人物生平\\n传记与足迹';" in html
    assert "const relatedGraphColumns = useMemo(() => {" in html
    assert "const payload = { ...node, isLeft: idx % 2 === 0 };" in html
    assert "const getRelatedGraphNodeMeta = (node) => {" in html
    assert "const relationText = /(同时代人物|相关人物)/.test(relation) ? '' : relation;" in html
    assert ".related-graph-core {" in html
    assert ".related-graph-core-dot {" in html
    assert ".related-graph-board {" in html
    assert ".related-graph-layout {" in html
    assert ".related-graph-entry {" in html
    assert ".related-graph-entry.is-left {" in html
    assert ".related-graph-entry-meta {" in html
    assert "人物关系一览，点击人物名跳转" in html
    assert "return getCanonicalPersonName(rawName) !== getCanonicalPersonName(data.person?.name);" in html
    assert "const isSameBookGraphRelation = (node) => {" not in html
    assert "同册共现" not in html
    assert "'苏东坡'" not in html.split("const centerPersonAliases = useMemo", 1)[1].split("const relatedCenterNode = useMemo", 1)[0]
    assert "related-graph-legend" not in html
    assert "中心人物在中间，相关人物按左右列展开" not in html
    assert "关系标签直接贴在人物卡片上，点击可跳转" not in html
    assert "纵向位置仅用于排版避让，不代表年代、亲疏或地理方向" not in html
    assert "radial-gradient(920px 520px at 8% 4%, rgba(26,115,232,0.18), transparent 56%)" in html
    assert "linear-gradient(140deg, #0f172a 0%, #14213d 58%, #10253f 100%)" in html
    assert "related-graph-edge-line" not in html
    assert "const getPresetSlots = (side, size) => {" not in html
    assert "edgePath: `M 50 50 Q ${controlX} ${controlY} ${placed.x} ${placed.y}`," not in html
    assert "const normalizePersonToken = (value) => (" in html
    assert "const centerPersonNameTokens = useMemo(() => new Set(" in html
    assert "const normalizePromptPlaceName = (loc) => {" in html
    assert "/(存疑|说法不一|不详|待考|未详|一说|或说|另说)/.test(raw)" in html
    assert "const placeName = findPromptPlaceName();" in html
    assert ".related-graph-board::before {" in html
    assert ".related-graph-board::after {" in html
    assert "grid-template-columns: minmax(0, 1fr) 160px minmax(0, 1fr);" in html
    assert "width: 156px;" in html
    assert ".related-graph-core-subtitle {" in html
    assert "font-size: 21px;" in html
    assert "0 0 0 10px color-mix(in srgb, var(--graph-accent) 10%, transparent)," in html
    assert "const relatedGraphCenterTitle = useMemo(" in html
    assert "const relatedGraphCenterSubtitle = relatedGraphCenterTitle === RELATED_GRAPH_CENTER_COPY ? '' : '人物生平';" in html
    assert '<div className="related-graph-core-name">{relatedGraphCenterTitle}</div>' in html
    assert '<div className="related-graph-core-subtitle">{relatedGraphCenterSubtitle}</div>' in html
    assert '<div className="related-graph-core-name">{RELATED_GRAPH_CENTER_COPY}</div>' not in html
    assert '<div className="related-graph-entry-name">{node.name}</div>' in html
    assert '<div className="related-graph-entry-dot" />' in html
    assert '<div className="related-graph-board">' in html
    assert "related-graph-avatar" not in html
    assert "related-graph-edge-label-text" not in html
    assert "getRelatedGraphEdgeLabel(node)" not in html
    assert "related-graph-meta" not in html
    assert "const labelRatio = 0.42;" not in html
    assert "if (size === 3) return side === 'left' ? [225, 180, 135] : [-45, 0, 45];" not in html


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

    assert "const warPattern = /(战争|战事|战场|交战|作战|参战|战役|会战|抗战|抗敌|起义|兵变|兵败|兵临|用兵|出兵|撤兵|领兵|率军|统军|攻城|守城|攻伐|讨伐|征讨|征战|交锋)/;" in html
    assert "if (warPattern.test(pool)) push('war', '战争');" in html
    assert "if (/(战|伐|兵|军|攻|守|起义|征讨|抗战|会战|战役|交锋)/.test(pool)) push('war', '战争');" not in html


def test_profile_page_template_uses_precise_travel_badge_rule():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const travelPattern = /(游历|巡游|巡幸|迁居|迁徙|迁往|迁至|迁到|出使|远行|远赴|流放|流寓|谪居|谪迁|入朝|赴任|奔赴|抵达|定居|南下|北上|东行|西行|启程)/;" in html
    assert "if (travelPattern.test(pool)) push('travel', '行旅');" in html
    assert "if (/(游|行|巡|迁|至|出使|远行|流放|谪|入朝|赴|抵达|定居)/.test(pool)) push('travel', '行旅');" not in html


def test_profile_page_template_uses_precise_politics_badge_rule():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const politicsPattern = /(任官|出任|赴任|主政|执政|从政|辅政|摄政|拜相|为相|宰相|丞相|尚书|刺史|太守|封侯|封王|称王|称帝|即位|登基|改革|变法|新政)/;" in html
    assert "if (politicsPattern.test(pool)) push('politics', '仕途');" in html
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


def test_render_profile_html_exposes_feedback_button_and_build_meta():
    """人物页应当带内容纠错入口，并向页面注入可识别的构建版本和构建时间。"""

    html = render_profile_html(
        {
            "person": {"name": "测试人物"},
            "locations": [],
            "highlights": {},
        }
    )

    assert "feedback-button" in html
    assert "page-footer" in html
    assert "openFeedbackDialog" in html
    assert "__BUILD_META__" in html
    assert "__BUILD_VERSION__" not in html
    assert "__BUILD_AT__" not in html
    assert "__BUILD_SOURCE_COMMIT__" not in html
    assert "__BUILD_COMPONENT__" not in html
    assert renderer.profile_template_signature() in html


def test_profile_page_template_supports_subtle_narrative_emphasis_for_description():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "renderNarrativeInline" in html
    assert "NARRATIVE_TRANSITION_RE" in html
    assert "NARRATIVE_TIME_RE" in html
    assert "NARRATIVE_IDENTITY_RE" in html
    assert "NARRATIVE_TURNING_SENTENCE_RE" in html
    assert "narrative-description" in html
    assert "idx < 2 ? 'is-lead' : 'is-body'" in html
    assert "narrative-sentence" in html
    assert "narrative-inline-identity" in html
    assert "narrative-inline-strong" in html
    assert "narrative-inline-time" in html
    assert "narrative-inline-place" in html
    assert "renderNarrativeLine(seg, idx)" in html
