import importlib
import sys
import typing


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

TEMPLATE_PATH = REPO_ROOT / "storymap" / "script" / "templates" / "profile_page.html"

import map_html_renderer as renderer
from map_html_renderer import render_profile_html
from artifacts import _extract_export_data_from_html
import profile_builder
import story_map


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
    assert "苏东坡" not in payload["personRedirects"]
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


def test_render_profile_html_includes_google_analytics_snippet():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "googletagmanager.com/gtag/js?id=G-B8F24PMY4F" in html
    assert "gtag('config', \"G-B8F24PMY4F\")" in html


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


def test_profile_template_signature_covers_render_dependency_sources():
    deps = renderer.profile_render_dependency_paths()
    names = {path.name for path in deps}

    assert "person_registry.py" in names
    assert "profile_builder.py" in names
    assert "generate_pure_story_map.py" in names


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


def test_timeline_card_click_uses_strict_map_focus():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const normalizeFocusOptions = raw => {" in html
    assert "controller.focusIndex(idx, {" in html
    assert "pulse: pulseNow" in html
    assert "strict" in html
    assert "applySelectionToMap(idx, loc, {" in html
    assert "stabilize: true" in html


def test_profile_template_declares_curved_segment_builder_before_usage():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "function buildCurvedSegmentPath(from, to, idx, prev, next) {" in html
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
    assert "if (birthplaceLabel) push(`籍贯：${birthplaceLabel}`);" in html


def test_profile_template_defines_journey_panel_sizes_before_effect_uses_them():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    panel_height_idx = html.index("const journeyPanelHeight = journeyFullscreenActive")
    sync_effect_idx = html.index("const syncMapViewport = () => {")

    assert panel_height_idx < sync_effect_idx
    assert "mapEl.style.height = journeyPanelHeight;" in html
    assert "mapEl.style.minHeight = journeyPanelMinHeight;" in html


def test_profile_template_persists_stage_key_point_labels_and_shows_all_segment_arrows():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const getPersistentLabelIndexes = () => {" in html
    assert "const stageRatios = total >= 10 ? [0.2, 0.4, 0.6, 0.8] : [0.25, 0.5, 0.75];" in html
    assert "const essential = getPersistentLabelIndexes();" in html
    assert "const stride = totalSegments >= 12 ? 3 : totalSegments >= 7 ? 2 : 1;" in html
    assert "if (item.distance >= 80 && order % stride === 0) keep.add(item.idx);" in html
    assert "showArrow: true," in html


def test_profile_template_zooms_out_single_point_story_to_show_basemap():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const defaultFocusZoom = locations.length <= 1 ? 5.6 : 10;" in html
    assert "const v = Number.isFinite(z) ? z : defaultFocusZoom;" in html
    assert "if (boundsPoints.length === 1) {" in html
    assert "map.easeTo({" in html
    assert "center: boundsPoints[0]" in html
    assert "zoom: focusZoom" in html


def test_profile_template_only_uses_fallback_overlay_when_maplibre_artifacts_are_missing():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "if (hasRenderableOverlayArtifacts()) {" in html
    assert "map.on('movestart', clearFallbackOverlay);" in html
    assert "map.on('zoomstart', clearFallbackOverlay);" in html
    assert "scheduleFallbackOverlayRender('move');" in html
    assert "scheduleFallbackOverlayRender('zoom');" in html


def test_static_site_notice_hides_on_localhost(monkeypatch):
    monkeypatch.setenv("MAP_STORY_STATIC_SITE", "1")
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert 'id="site-mode-notice"' in html
    assert "const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');" in html
    assert "const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);" in html
    assert "if (notice) notice.style.display = 'none';" in html


def test_runtime_map_config_loaders_treat_private_network_hosts_as_dev_hosts():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith('.local');" in html
    assert "window.MAP_STORY_STATIC_SITE !== true || isDevHost" in html


def test_static_profile_page_tries_local_ai_proxy_on_localhost():
    html = render_profile_html({"person": {"name": "测试人物"}, "locations": [], "highlights": {}})

    assert "if ((!staticSite || isLocalHost) && window.location && window.location.protocol !== 'file:') {" in html
    assert "if (!staticSite || isLocalHost) {" in html
    assert "pushUrl('http://127.0.0.1:8765/api/ai/proxy');" in html


def test_map_html_renderer_type_hints_resolve_for_canonical_person_name():
    registry = importlib.import_module("storymap.script.person_registry")
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


def test_load_profile_prefers_literary_persons_own_work_for_short_review():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "李白.md").read_text(encoding="utf-8")

    profile = story_map.load_profile_from_md(md, allow_geocode=False)

    assert "犬吠水声中" in str(profile["person"].get("shortReview") or "")


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
    assert "fullscreenChatRestoreRef" in html
    assert ".map-compact-action-button {" in html
    assert "width: 52px;" in html
    assert ".map-bottom-button.is-accent-export {" in html
    assert 'className="h-6 w-6 shrink-0"' in html
    assert 'viewBox="0 0 24 24"' in html
    assert 'absolute bottom-4 right-8 z-[1000] map-floating-controls flex items-center gap-2' in html
    assert 'data-export-ignore="true"' in html
    assert 'label="底图"' in html
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
    assert "map.on('idle', () => healMapLibreOverlaysIfMissing('idle'))" in html
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
    assert 'className="flex min-h-full flex-col justify-end gap-3"' in html
    assert "draggingRef.current = 'horizontal';" in html
    assert "draggingRef.current = 'vertical';" in html


def test_profile_page_template_defers_map_init_until_viewport_or_manual_trigger():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const [mapLoadState, setMapLoadState] = useState('idle');" in html
    assert "const [mapInitRequestTick, setMapInitRequestTick] = useState(0);" in html
    assert "const requestMapInitialization = React.useCallback((reason = 'manual') => {" in html
    assert "new window.IntersectionObserver((entries) => {" in html
    assert "requestMapInitialization('viewport');" in html
    assert "requestMapInitialization('fallback');" in html
    assert "if (mapInitRequestTick <= 0 || mapRef.current) return () => { disposed = true; };" in html
    assert "data-testid=\"profile-map-lazy-overlay\"" in html
    assert "地图进入视口后也会自动加载" in html
    assert "onClick={() => requestMapInitialization('manual')}" in html
    assert "{mapReady ? (" in html
    assert "{mapReady && mapStatusNotice ? (" in html


def test_profile_page_template_prefers_geovis_without_vector_probe_preflight():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "await ((window.__MAP_STORY_GEOVIS__ && window.__MAP_STORY_GEOVIS__.ensureMapLibre) || _ensureMapLibre)();" in html
    assert "probeGeoVisLayerType(geovis, 'vector')" not in html
    assert "if (mode === 'vector') {" in html
    assert "fallbackToMapLibreMode(`${label} 暂不可用，已保留当前 GeoVis 底图。`, mapLayerType);" in html
    assert "title: '已切换到高德备用底图'" in html
    assert "label: '恢复 GeoVis'" in html
    assert "label: `重试${describeLayerType(attemptedLayerType)}`" in html


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
    assert "const isSameBookGraphRelation = (node) => {" in html
    assert "sourceType === 'same_book' || /同册共现/.test(relationLabel)" in html
    assert "const RELATED_GRAPH_CENTER_COPY = '人物生平\\n传记与足迹';" in html
    assert "const relatedGraphColumns = useMemo(() => {" in html
    assert "const payload = { ...node, isLeft: idx % 2 === 0 };" in html
    assert "const getRelatedGraphNodeMeta = (node) => {" in html
    assert ".related-graph-core {" in html
    assert ".related-graph-core-dot {" in html
    assert ".related-graph-board {" in html
    assert ".related-graph-layout {" in html
    assert ".related-graph-entry {" in html
    assert ".related-graph-entry.is-left {" in html
    assert ".related-graph-entry-meta {" in html
    assert "人物关系一览，点击人物名跳转" in html
    assert "return getCanonicalPersonName(rawName) !== getCanonicalPersonName(data.person?.name);" in html
    assert "if (isSameBookGraphRelation(node)) return false;" in html
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
    assert "el.className = 'map-pulse-marker';" in html
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
    assert html.count("showArrow: true,") >= 2
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
    assert 'class="map-point-label-text"' in html
    assert 'class="map-point-label-badge"' in html
    assert 'class="map-point-label-name"' in html
    assert "font-size: 11px;" in html
    assert "maplibre: [0, isEndpoint ? -24 : -20]," in html
    assert "amap: [0, isEndpoint ? -34 : -28]," in html


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
    """人物页应当带反馈错误按钮，并向页面注入可识别的构建版本和构建时间。"""

    html = render_profile_html(
        {
            "person": {"name": "测试人物"},
            "locations": [],
            "highlights": {},
        }
    )

    assert "feedback-button" in html
    # Babel 编译后中文会被转成 \uXXXX 转义（大写十六进制），
    # 同时兼容未编译/编译后两种形态。
    assert (
        "反馈错误" in html
        or "\\u53CD\\u9988\\u9519\\u8BEF" in html
        or "\\u53cd\\u9988\\u9519\\u8bef" in html
    )
    assert "openFeedbackDialog" in html
    assert "__BUILD_META__" in html
    assert "__BUILD_VERSION__" not in html
    assert "__BUILD_AT__" not in html
    assert renderer.profile_template_signature() in html
