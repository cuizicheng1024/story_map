import argparse
import importlib
from pathlib import Path


def test_render_index_html_emits_valid_regex_literals():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert r'replace(/^\\/+/, "")' not in html
    assert r'replace(/\\/+$/, "")' not in html
    assert r'replace(/^今\\s*/g, "")' not in html
    assert r'replace(/^约\\s*/g, "")' not in html
    assert r'replace(/^公元前?\\d+年\\s*/g, "")' not in html
    assert r'replace(/^\/+/, "")' in html
    assert r'replace(/\/+$/, "")' in html
    assert r'replace(/^今\s*/g, "")' in html
    assert r'replace(/^约\s*/g, "")' in html
    assert r'replace(/^公元前?\d+年\s*/g, "")' in html
    assert r'window.__openPerson(\'' not in html
    assert "const clearTaskPoll = () => {" in html
    assert "const scheduleTaskPoll = (taskId, generation, tick, ms = 900) => {" in html
    assert "const resolveTaskResultHtml = (result, fallbackPerson) => {" in html
    assert "if (activeTaskPollId === id) return;" in html
    assert "scheduleTaskPoll(id, generation, tick, 900);" in html
    assert "const targetHtml = resolveTaskResultHtml(result, person);" in html
    assert "snapshot.exists !== true" in html
    assert 'if (st === "partial_failed")' in html


def test_resolve_main_role_band_prefers_primary_identity_field():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="**主要身份**：政治家、军事家、谋略家\n",
        domain_tags=[],
        review="",
        quote="",
    )

    assert band == "politics"
    assert label == "政治家"


def test_resolve_main_role_band_can_fallback_to_domain_tags():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="",
        domain_tags=["诗人", "书法家"],
        review="",
        quote="",
    )

    assert band == "literature"
    assert label == "诗人"


def test_resolve_main_role_band_places_philosophers_into_academic_band():
    module = importlib.import_module("tools.build_stellar_homepage")

    band, label = module._resolve_main_role_band(
        md_text="**主要身份**：哲学家、教育家、思想家\n",
        domain_tags=[],
        review="",
        quote="",
    )

    assert band == "academic"
    assert label == "哲学家"


def test_build_payload_meta_prefers_github_env(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.setattr(module, "_now", lambda: "2026-06-10 12:00:00")
    monkeypatch.setattr(module, "_git_head", lambda: "local-head-sha")
    monkeypatch.setenv("GITHUB_SHA", "deploy-sha")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    payload_meta = module._build_payload_meta()

    assert payload_meta == {
        "generated_at": "2026-06-10 12:00:00",
        "source_commit": "deploy-sha",
        "pages_run_id": 123456,
        "pages_run_attempt": 2,
    }


def test_prepare_home_payload_for_output_merges_defaults(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.setattr(module, "_build_payload_meta", lambda: {"generated_at": "2026-06-14 00:00:00"})

    payload = module._prepare_home_payload_for_output(
        {"min_year": -221, "nodes": [{"person": "秦始皇"}], "edges": [{"a": 0, "b": 0}]},
        default_start=100,
        default_end=1600,
    )

    assert payload["generated_at"] == "2026-06-14 00:00:00"
    assert payload["min_year"] == -221
    assert payload["max_year"] == module.MAX_YEAR
    assert payload["default_start"] == 100
    assert payload["default_end"] == 1600
    assert payload["nodes"] == [{"person": "秦始皇"}]
    assert payload["edges"] == [{"a": 0, "b": 0}]
    assert payload["kg_edges"] == []
    assert payload["search_capabilities"]["aliases"] is True


def test_render_index_html_uses_sparser_tick_config_for_recent_ranges():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const pickTickConfig = (start, end) => {" in html
    assert "const recentRatio = overlapYears(start, end, 1840, maxYear) / span;" in html
    assert "const contemporaryRatio = overlapYears(start, end, 1911, maxYear) / span;" in html
    assert "const maxLabels = contemporaryRatio >= 0.7 ? 5 : (recentRatio >= 0.55 ? 6 : 9);" in html
    assert "const minPxPerLabel = contemporaryRatio >= 0.7 ? 108 : (recentRatio >= 0.55 ? 88 : 56);" in html


def test_main_can_export_homepage_from_neo4j_without_story_markdown(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    spotlight = tmp_path / "spotlight.json"
    spotlight.write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        spotlight=str(spotlight),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="neo4j",
    )

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: [])
    monkeypatch.setattr(module, "person_redirects", lambda names=None: {})
    monkeypatch.setattr(
        module,
        "load_home_graph_payload_with_source",
        lambda *args, **kwargs: (
            {"min_year": -200, "max_year": 200, "nodes": [{"person": "张骞"}], "edges": []},
            "neo4j",
        ),
    )
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0


def test_main_fails_when_explicit_neo4j_source_is_unavailable(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    spotlight = tmp_path / "spotlight.json"
    spotlight.write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        spotlight=str(spotlight),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="neo4j",
    )

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: [])
    monkeypatch.setattr(module, "person_redirects", lambda names=None: {})
    monkeypatch.setattr(module, "load_home_graph_payload_with_source", lambda *args, **kwargs: ({}, ""))

    assert module.main() == 1
    assert '"error": "neo4j graph payload unavailable"' in capsys.readouterr().out


def test_render_index_html_includes_pixel_progress_panel_for_live_generation():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'id="pixelGenPanel" class="pixel-progress-shell"' in html
    assert 'id="pixelGenToggle"' in html
    assert 'id="pixelGenStatusBadge"' in html
    assert 'id="pixelGenSpeech"' in html
    assert 'id="pixelGenAgents"' in html
    assert 'id="pixelGenDetailCard"' in html
    assert "pixel-ocelot-monitor" not in html
    assert "pixel-progress-scene-light" in html
    assert 'id="pixelGenScene"' in html
    assert 'id="pixelGenSceneTitle"' in html
    assert "Story Console" in html
    assert ">橙子Agent</div>" in html
    assert ">空闲中</div>" in html
    assert 'aria-expanded="false"' in html
    assert 'id="pixelGenBody" class="pixel-progress-body" style="display:none"' in html
    assert "展开看板" in html
    assert "流程阶段" in html
    assert "执行模块" in html
    assert "const PIXEL_STAGE_FLOW = [" in html
    assert "const PIXEL_AGENT_CARDS = [" in html
    assert "const PIXEL_IDLE_STATES = [" in html
    assert "const updatePixelProgressPanel = (patch = {}) => {" in html
    assert 'const $pixelGenToggle = document.getElementById("pixelGenToggle");' in html
    assert 'const $pixelGenStatusBadge = document.getElementById("pixelGenStatusBadge");' in html
    assert 'const $pixelGenScene = document.getElementById("pixelGenScene");' in html
    assert 'const $pixelGenSceneTitle = document.getElementById("pixelGenSceneTitle");' in html
    assert 'const $pixelGenSpeech = document.getElementById("pixelGenSpeech");' in html
    assert 'const $pixelGenDetailCard = document.getElementById("pixelGenDetailCard");' in html
    assert 'let pixelGenCollapsed = true;' in html


def test_render_index_html_hides_hu_huanyong_midpoint_dot():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "胡焕庸线" in html
    assert "new window.AMap.CircleMarker({" not in html
    assert 'fillColor: "rgba(249,115,22,0.92)"' not in html
    assert 'visible: true,' in html
    assert 'setPixelPanelCollapsed(true);' in html
    assert 'updatePixelProgressPanel(pixelGenState);' in html
    assert 'const resolvePixelStageLabel = (status, stageKey) => {' in html
    assert 'if (status === "idle") return String(pixelGenState.idleStageLabel || "").trim() || "空闲中";' in html
    assert 'const resolvePixelBadgeClass = (status) => {' in html
    assert 'const resolvePixelStatusText = (status) => {' in html
    assert 'if (status === "idle") return "待命";' in html
    assert 'const basePercent = status === "idle"' in html
    assert '$pixelGenToggle.textContent = pixelGenCollapsed ? "+" : "-";' in html
    assert 'const escapePixelLogHtml = (value) => {' in html
    assert 'const safeLabelText = escapePixelLogHtml(labelText);' in html
    assert 'escapePixelLogHtml(detail)' in html
    assert 'renderPixelProgressLog(status, progress);' in html
    assert 'speechText: next.speech,' in html


def test_render_index_html_uses_orange_image_workbench_pet():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert module.HOMEPAGE_PET_ASSET_OUTPUT_NAME == "orange.png"
    assert 'class="pixel-orange-pet-wrap"' in html
    assert 'class="pixel-orange-pet-img"' in html
    assert './orange.png' in html
    assert 'alt="橙子工位形象"' in html
    assert "pixel-orange-pet-fallback" in html
    assert '>橙子Agent<' in html
    assert "吃猫条" not in html
    assert 'data-idle-scene="idle"' in html
    assert "box-shadow:" in html


def test_render_index_html_uses_post_generate_for_missing_people():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const fetchWithTimeout = (url, ms, init) => {' in html
    assert 'const generateUrl = apiUrl("generate");' in html
    assert 'fetchWithTimeout(generateUrl, 12000, { method: "POST"' in html
    assert 'body: JSON.stringify({ person })' in html
    assert 'apiUrl("generate?person="' not in html


def test_render_index_html_falls_back_to_local_fastapi_api_base_for_static_preview():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const resolvedApiBase = (() => {' in html
    assert 'const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "::1" || host.endsWith(".localhost");' in html
    assert 'const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);' in html
    assert 'const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith(".local");' in html
    assert 'return loc.protocol + "//" + runtimeHost + ":8765";' in html
    assert 'if (resolvedApiBase) {' in html
    assert 'return resolvedApiBase.replace(/\\/+$/, "") + "/" + rel;' in html


def test_render_index_html_normalizes_generated_html_paths_to_leaf_filename():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const cleaned = raw.split("#")[0].split("?")[0].replace(/\\\\/g, "/").replace(/^[.\\/]+/, "");' in html
    assert 'const parts = cleaned.split("/").filter(Boolean);' in html
    assert 'const leaf = parts.length ? parts[parts.length - 1] : "";' in html
    assert 'return /\\.html?$/i.test(leaf) ? leaf : "";' in html


def test_render_index_html_uses_google_palette_for_pixel_progress_panel():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert ".pixel-progress-lamp.is-idle {" in html
    assert ".pixel-progress-badge.is-idle {" in html
    assert "#4285f4" in html
    assert "#34a853" in html
    assert "#ea4335" in html
    assert "#fbbc04" in html
    assert "linear-gradient(90deg, #4285f4 0%, #ea4335 34%, #fbbc04 68%, #34a853 100%)" in html


def test_render_index_html_uses_shared_person_tooltip_model():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const buildPersonTooltipModel = (node, options = {}) => {" in html
    assert "const tipModel = buildPersonTooltipModel(n, { fallbackName: '相关人物' });" in html
    assert 'const rowHtml = tipModel.rows.map((row) => `<div class="text-white/70 text-[11px] mt-1">${esc(row.label)}：${esc(row.value)}</div>`).join("");' in html
    assert "const personTooltipCleanTaglineText = (s) => String(s || '')" in html
    assert ".replace(/^(?:人物)?短评\\s*[：:]\\s*/u, '')" in html


def test_render_index_html_separates_default_window_from_last_manual_window():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const LEGACY_TIME_WINDOW_KEY = "stellar_time_window_v2";' in html
    assert 'const LAST_MANUAL_TIME_WINDOW_KEY = "stellar_last_manual_time_window_v1";' in html
    assert 'localStorage.removeItem(LEGACY_TIME_WINDOW_KEY);' in html
    assert 'localStorage.setItem(LAST_MANUAL_TIME_WINDOW_KEY, JSON.stringify({' in html
    assert 'saved_at: Date.now(),' in html
    assert 'timeWindowSignature = [minYear, maxYear, startYear, endYear].join(":");' in html
    assert 'const savedWin = readTimeWindow();' not in html


def test_render_index_html_uses_china_overview_for_default_and_reset_map_view():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const CHINA_OVERVIEW_CENTER = [104.5, 36.0];" in html
    assert "const CHINA_OVERVIEW_ZOOM = 3.9;" in html
    assert "center: CHINA_OVERVIEW_CENTER," in html
    assert "zoom: CHINA_OVERVIEW_ZOOM," in html
    assert "if (amap) amap.setZoomAndCenter(CHINA_OVERVIEW_ZOOM, CHINA_OVERVIEW_CENTER);" in html


def test_render_index_html_keeps_searched_map_person_visible_outside_time_window():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const forceVisible = idx >= 0 && idx === hiIdx;" in html
    assert "if (onlyActiveMarkers && !active && !forceVisible) {" in html
    assert "const emph = active || forceVisible;" in html


def test_render_index_html_shows_person_info_on_map_marker_hover():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const buildMapPersonInfoHtml = (n) => {" in html
    assert 'id="mapTip" class="tooltip hidden"' in html
    assert "const showMapTip = (n, clientX, clientY) => {" in html
    assert "const resolveMapTipClientPoint = (evt, lng, lat) => {" in html
    assert 'mk.on("mouseover", (evt) => {' in html
    assert 'mk.on("mousemove", (evt) => {' in html
    assert "showMapTip(n, pos.clientX, pos.clientY);" in html
    assert 'mk.on("mouseout", () => {' in html
    assert "closeMapTip();" in html
    assert "if (infoWin) infoWin.close();" in html
    assert "const markerSvg = (sz, fill, glow, emph) => {" in html
    assert "const createMarkerContent = (n, lng, lat) => {" in html
    assert "const active = inWindow(n);" in html
    assert "const initialFill = active ? accent : accentSoft;" in html
    assert "el.innerHTML = markerSvg(initialSize, initialFill, initialGlow, active);" in html
    assert "if (onlyActiveMarkers && !inWindow(n)) {" in html
    assert 'el.addEventListener("mouseenter", show);' in html
    assert 'plugin=AMap.Geocoder' in html
    assert 'MarkerCluster' not in html
    assert 'const sz = dim ? 16 : (emph ? 20 : 18);' in html
    assert "it.mk.setContent(it.el);" in html
    assert 'const button = document.createElement("button");' in html
    assert 'button.addEventListener("click", () => {' in html
    assert 'openPerson(n && n.person ? n.person : "");' in html


def test_render_index_html_initializes_map_markers_with_dynasty_colors_and_window_visibility():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const active = inWindow(n);" in html
    assert "const base = colorByYear(n.time_year);" in html
    assert "const accent = base.startsWith(\"#\") ? hexToRgba(base, 0.92) : base;" in html
    assert "const accentSoft = base.startsWith(\"#\") ? hexToRgba(base, 0.62) : base;" in html
    assert "const initialFill = active ? accent : accentSoft;" in html
    assert "el.innerHTML = markerSvg(initialSize, initialFill, initialGlow, active);" in html
    assert "if (onlyActiveMarkers && !inWindow(n)) {" in html
    assert "try { mk.hide(); } catch (_) {}" in html


def test_render_index_html_keeps_marker_svg_in_shared_scope_for_map_refresh():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    marker_svg_idx = html.index("const markerSvg = (sz, fill, glow, emph) => {")
    init_map_idx = html.index("const initMapOnce = () => {")
    update_markers_idx = html.index("const updateMapMarkers = () => {")

    assert marker_svg_idx < init_map_idx
    assert marker_svg_idx < update_markers_idx
    assert "it.el.innerHTML = markerSvg(sz, fill, glow, emph);" in html


def test_render_index_html_uses_rectangular_city_labels_and_higher_hu_line_tag():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const offsetDeg = 1.32;" in html
    assert 'offset: new window.AMap.Pixel(0, -5),' in html
    assert "mohe[0] + (tengchong[0] - mohe[0]) / 3" in html
    assert "mohe[1] + (tengchong[1] - mohe[1]) / 3" in html
    assert 'borderRadius: "2px",' in html


def test_render_index_html_routes_timeline_drag_from_document_capture():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const isEventWithinRail = (e) => {" in html
    assert "document.addEventListener(\"pointerdown\", routeDown, true);" in html
    assert "document.addEventListener(\"mousedown\", routeDown, true);" in html
    assert "$rail.addEventListener(\"pointerdown\", onDown);" not in html
    assert "$rail.addEventListener(\"mousedown\", onDown);" not in html


def test_render_index_html_omits_static_demo_banner():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "静态演示版" not in html
    assert "当前页面运行于 GitHub Pages 等静态站环境" not in html


def test_render_index_html_removes_map_top5_footer_and_keeps_panes_same_height():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert '中国范围内：' not in html
    assert ".distribution-pane {" in html
    assert "height: 500px;" in html
    assert ".distribution-frame {" in html
    assert '#c {' in html
    assert 'id="graphPane" class="relative distribution-pane"' in html
    assert 'class="rounded-xl overflow-hidden border border-white/10 distribution-frame"' in html
    assert '<canvas id="c" width="900" height="500"></canvas>' in html
    assert 'id="mapPane" class="relative hidden distribution-pane"' in html
    assert 'id="chinaMap" class="rounded-xl overflow-hidden border border-white/10 distribution-frame"' in html


def test_render_index_html_left_aligns_home_title_block():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "align-items: flex-start;" in html
    assert "text-align: left;" in html
    assert ".home-title-mark::before" not in html


def test_scan_latest_html_prefers_canonical_person_page_over_pure_snapshot(tmp_path):
    module = importlib.import_module("tools.build_stellar_homepage")
    canonical = tmp_path / "苏轼.html"
    snapshot = tmp_path / "苏轼__pure__20260610_214133.html"
    payload = '{"person":{"birth":{"lat":30.0,"lng":120.0},"death":{}}}'
    html = f"<script>const data = {payload}; window.__EXPORT_DATA__ = data;</script>"
    snapshot.write_text(html, encoding="utf-8")
    canonical.write_text(html, encoding="utf-8")
    # Make the snapshot look newer to ensure canonical naming still wins.
    snapshot.touch()
    canonical.touch()
    latest = module._scan_latest_html(Path(tmp_path))
    assert latest["苏轼"].file == "苏轼.html"


def test_render_person_alias_redirect_html_preserves_hash_and_targets_canonical_page():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_person_alias_redirect_html("苏东坡", "苏轼")

    assert "encodeURIComponent(canonical + \".html\") + search + hash" in html
    assert "window.location.replace(target);" in html
    assert "“苏东坡”为“苏轼”的别名，正在跳转" in html
    assert 'meta http-equiv="refresh"' not in html
    assert '<noscript>' in html


def test_canonical_story_name_entries_preserves_real_story_sources():
    module = importlib.import_module("tools.build_stellar_homepage")

    entries = module._canonical_story_name_entries(["苏轼", "苏东坡", "李白"])

    assert entries == [
        ("李白", "李白", []),
        ("苏东坡", "苏东坡", []),
        ("苏轼", "苏轼", []),
    ]


def test_canonical_story_name_entries_keeps_redirect_aliases_for_real_story_search():
    module = importlib.import_module("tools.build_stellar_homepage")

    entries = module._canonical_story_name_entries(["苏轼"])

    assert entries == [("苏轼", "苏轼", ["苏东坡"])]


def test_scan_people_from_story_md_filters_non_authentic_markdown(tmp_path):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    people = module._scan_people_from_story_md(story_dir)

    assert people == ["苏轼"]


def test_clean_review_text_strips_short_review_prefixes():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._clean_review_text("- 短评：浪漫主义诗歌高峰。") == "浪漫主义诗歌高峰。"
    assert module._clean_review_text("1. 人物短评: 千秋功过，后人评说。") == "千秋功过，后人评说。"
