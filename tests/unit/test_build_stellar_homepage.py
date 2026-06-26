import argparse
import importlib
import json
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
    assert '<link rel="icon" type="image/png" sizes="32x32" href="./orange.png?v=20260617-tab" />' in html
    assert '<link rel="shortcut icon" href="./orange.png?v=20260617-tab" />' in html
    assert '<link rel="apple-touch-icon" href="./orange.png?v=20260617-tab" />' in html
    assert "const clearTaskPoll = () => {" in html
    assert "const scheduleTaskPoll = (taskId, generation, tick, ms = 900) => {" in html
    assert "const probeGeneratedPersonHtml = async (personName) => {" in html
    assert "const resolveTaskResultHtml = (result, fallbackPerson) => {" in html
    assert "if (activeTaskPollId === id) return;" in html
    assert "scheduleTaskPoll(id, generation, tick, 900);" in html
    assert "const targetHtml = resolveTaskResultHtml(result, person);" in html
    assert "snapshot.exists !== true" in html
    assert "let missingSnapshotCount = 0;" in html
    assert "if (missingSnapshotCount <= 8) {" in html
    assert "const summary = \"任务状态同步中，请稍候…\";" in html
    assert "const generatedHtml = await probeGeneratedPersonHtml(person);" in html
    assert 'if (st === "partial_failed")' in html
    assert "let personPageOpened = false;" in html
    assert 'let pendingPersonPageTab = null;' in html
    assert 'const resolveStarOfficeUrl = (personName, taskId = "") => {' in html
    assert 'const ensurePendingPersonTab = (personName) => {' in html
    assert 'const navigatePendingPersonTabToOffice = (personName, taskId = "") => {' in html
    assert 'const navigatePendingPersonTabToHtml = (personName, file) => {' in html
    assert 'ensurePendingPersonTab(q);' in html
    assert 'navigatePendingPersonTabToOffice(person, taskId);' in html
    assert 'navigatePendingPersonTabToHtml(person, generatedHtml) || navigateToRelativeHtml(generatedHtml, { newTab: true });' in html
    assert 'personPageOpened = navigatePendingPersonTabToHtml(person, targetHtml) || navigateToRelativeHtml(targetHtml, { newTab: true });' in html
    assert 'if (archiveState === "queued" || archiveState === "running") {' in html
    assert 'const summary = "人物页已打开，群星首页与知识图谱正在后台补齐…";' in html
    assert 'scheduleTaskPoll(id, generation, tick, 1200);' in html
    assert 'window.location.reload();' in html
    assert "学习演示版" not in html
    assert 'const SEARCH_HINT_LINE_ONE_HTML = \'<span class="home-search-hint-line"><strong>1. 内置人教版教材500+历史人物，可以直接访问</strong></span>\';' in html
    assert 'const SEARCH_HINT_LINE_TWO_HTML = \'<span class="home-bili-highlight">2. 欢迎B站用户投币 投币 三连：<a href="https://www.bilibili.com/video/BV1u3LX66Eh7/" target="_blank" rel="noopener noreferrer">「我把2000年中国名人做成了动态地图，还能和李白聊天」</a></span>\';' in html
    assert 'const DEFAULT_SEARCH_HINT_HTML = SEARCH_HINT_LINE_ONE_HTML + SEARCH_HINT_LINE_TWO_HTML;' in html
    assert 'const buildSearchHintHtml = (runtimeLine = "") => {' in html
    assert '$searchHint.innerHTML = buildSearchHintHtml(runtimeLine);' in html


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


def test_extract_basic_place_from_md_reads_native_place_and_modern_name():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_basic_place_from_md(
        "- **籍贯**：广东新会（今广东省江门市新会区）\n",
        ("籍贯", "祖籍"),
    )

    assert raw == "广东新会今广东省江门市新会区"
    assert ancient == "广东新会"
    assert modern == "广东省江门市新会区"


def test_extract_basic_place_from_md_can_fallback_to_overview_native_place():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_basic_place_from_md(
        "### 生平概述\n王安石，字介甫，号半山，祖籍抚州临川，出生于临江军清江县（今江西省樟树市）。\n",
        ("籍贯", "祖籍"),
    )

    assert raw == "抚州临川"
    assert ancient == "抚州临川"
    assert modern == ""


def test_build_payload_meta_prefers_github_env(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.setattr(module, "_now", lambda: "2026-06-10 12:00:00")
    monkeypatch.setenv("GITHUB_SHA", "deploy-sha")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("STORYMAP_BUILD_VERSION", "build-v1")

    payload_meta = module._build_payload_meta()

    assert payload_meta["artifact_component"] == "stellar_homepage"
    assert payload_meta["artifact_version"] == "build-v1"
    assert payload_meta["build_version"] == "build-v1"
    assert payload_meta["build_at"] == "2026-06-10T12:00:00"
    assert payload_meta["generated_at"] == "2026-06-10T12:00:00"
    assert payload_meta["source_commit"] == "deploy-sha"
    assert payload_meta["pages_run_id"] == 123456
    assert payload_meta["pages_run_attempt"] == 2


def test_analytics_head_html_requires_explicit_measurement_id(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.delenv("MAP_STORY_GA_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)

    html = module._analytics_head_html()

    assert "googletagmanager.com/gtag/js" not in html


def test_analytics_head_html_uses_explicit_measurement_id(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.delenv("MAP_STORY_GA_MEASUREMENT_ID", raising=False)
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-TEST123456")

    html = module._analytics_head_html()

    assert "googletagmanager.com/gtag/js?id=G-TEST123456" in html
    assert "gtag('config', \"G-TEST123456\")" in html


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
    assert payload["nodes"] == [{"person": "秦始皇", "is_foreign": False}]
    assert payload["edges"] == [{"a": 0, "b": 0}]
    assert payload["kg_edges"] == []
    assert payload["search_capabilities"]["aliases"] is True


def test_split_home_payload_for_delivery_moves_heavy_fields_into_detail_payload(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")

    monkeypatch.setattr(module, "_build_payload_meta", lambda: {"generated_at": "2026-06-20 10:00:00"})
    payload = {
        "nodes": [
            {
                "person": "苏轼",
                "file": "苏轼.html",
                "quote": "一蓑烟雨任平生。",
                "review": "北宋文学家。",
                "works": ["赤壁赋"],
                "work_summaries": {"赤壁赋": {"title": "赤壁赋", "summary": "前后赤壁之间的精神展开。"}},
                "relations": ["黄庭坚"],
                "relations_meta": [{"name": "黄庭坚", "label": "师友"}],
                "domain_tags": ["诗人", "词人"],
                "risk_level": "low",
                "audit_pass": True,
                "audit_uncertain": False,
            }
        ],
        "edges": [],
        "kg_edges": [],
    }

    core_payload, detail_payload = module._split_home_payload_for_delivery(payload)

    assert core_payload["nodes"][0]["person"] == "苏轼"
    assert core_payload["nodes"][0]["quote"] == "一蓑烟雨任平生。"
    assert "review" not in core_payload["nodes"][0]
    assert "work_summaries" not in core_payload["nodes"][0]
    assert detail_payload["generated_at"] == "2026-06-20 10:00:00"
    assert detail_payload["count"] == 1
    assert detail_payload["fields"] == list(module.HOME_DETAIL_NODE_FIELDS)
    assert detail_payload["nodes"][0]["person"] == "苏轼"
    assert detail_payload["nodes"][0]["review"] == "北宋文学家。"
    assert "work_summaries" in detail_payload["nodes"][0]


def test_write_homepage_outputs_writes_core_detail_and_index(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()

    monkeypatch.setattr(module, "_sync_vendor_assets", lambda _dir: None)
    monkeypatch.setattr(
        module,
        "_sync_embedded_apps",
        lambda out_dir: (out_dir / "orange-office.html").write_text("<html>office</html>", encoding="utf-8"),
    )
    monkeypatch.setattr(module, "_sync_homepage_pet_asset", lambda _dir: None)
    monkeypatch.setattr(module, "write_normalized_graph_json", None)
    monkeypatch.setattr(module, "should_sync_to_neo4j", None)
    monkeypatch.setattr(module, "sync_graph_payload_to_neo4j", None)

    payload = {
        "nodes": [
            {
                "person": "李白",
                "file": "李白.html",
                "quote": "天生我材必有用。",
                "review": "浪漫主义诗歌高峰。",
                "works": ["将进酒"],
                "work_summaries": {"将进酒": {"title": "将进酒", "summary": "豪放诗篇。"}},
            }
        ],
        "edges": [],
        "kg_edges": [],
    }

    outputs = module._write_homepage_outputs(
        story_map_dir=story_map_dir,
        out_index_name="index.html",
        out_data_name="stellar_home_data.json",
        title="故事地图",
        payload=payload,
        active_redirects={},
        sync_payload_to_neo4j=False,
    )

    core_payload = json.loads((story_map_dir / "stellar_home_data.json").read_text(encoding="utf-8"))
    detail_payload = json.loads((story_map_dir / "stellar_home_data_detail.json").read_text(encoding="utf-8"))
    html = (story_map_dir / "index.html").read_text(encoding="utf-8")

    assert outputs["data"].endswith("stellar_home_data.json")
    assert outputs["detail"].endswith("stellar_home_data_detail.json")
    assert core_payload["nodes"][0]["person"] == "李白"
    assert "review" not in core_payload["nodes"][0]
    assert "work_summaries" not in core_payload["nodes"][0]
    assert detail_payload["nodes"][0]["review"] == "浪漫主义诗歌高峰。"
    assert (story_map_dir / "orange-office.html").read_text(encoding="utf-8") == "<html>office</html>"
    assert 'const DATA_DETAIL_FILE = "stellar_home_data_detail.json";' in html
    assert "loadHomeDetailData()" in html


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

    assert 'id="pixelGenPanel" class="pixel-progress-shell is-collapsed"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="系统状态：待命中"' in html
    assert 'title="系统状态：只读展示，不能手动暂停或恢复"' in html
    assert 'id="pixelGenToggle"' in html
    assert 'id="pixelGenStatusBadge"' in html
    assert 'id="pixelGenCompactText"' in html
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
    assert 'id="pixelGenBody" class="pixel-progress-body is-star-office-only" style="display:none"' in html
    assert "查看 Orange Office 详情（状态只读）" in html
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
    assert 'const $pixelGenCompactText = document.getElementById("pixelGenCompactText");' in html
    assert 'id="pixelGenOpsBar" class="pixel-progress-opsbar"' in html
    assert 'id="pixelGenOpsServe" class="pixel-progress-opschip is-muted"' in html
    assert 'id="pixelGenOpsGenerate" class="pixel-progress-opschip is-muted"' in html
    assert 'id="pixelGenOpsQueue" class="pixel-progress-opschip is-muted"' in html
    assert 'id="pixelGenOpsDeps" class="pixel-progress-opschip is-muted"' in html
    assert 'let pixelGenCollapsed = true;' in html
    assert 'let pixelGenPinnedExpanded = false;' in html
    assert 'let pixelGenHovering = false;' in html
    assert '$pixelGenPanel.classList.toggle("is-collapsed", pixelGenCollapsed);' in html
    assert ".pixel-progress-shell.is-collapsed {" in html
    assert "width: min(136px, calc(100vw - 24px));" in html
    assert "border-radius: 999px;" in html
    assert ".pixel-progress-opsbar {" in html
    assert "const syncRuntimeOpsBoard = () => {" in html
    assert 'const STAR_OFFICE_URL = "./orange-office.html";' in html
    assert "const STAR_OFFICE_OPEN_IN_NEW_TAB = true;" in html


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
    assert 'if (runtimeAvailability.mode === "browser_only") return "只读";' in html
    assert 'if (runtimeAvailability.mode === "generate_paused") return "降级";' in html
    assert 'const resolvePixelCompactText = (status, stageKey) => {' in html
    assert 'const basePercent = status === "idle"' in html
    assert '$pixelGenToggle.textContent = pixelGenCollapsed ? "+" : "-";' in html
    assert 'const openStarOfficeInNewTab = () => {' in html
    assert 'const nextTab = window.open(STAR_OFFICE_URL, "_blank", "noopener");' in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-caption {" in html
    assert "display: none;" in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-meta {" in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-badge {" in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-actions {" in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-panel::before {" in html
    assert ".pixel-progress-shell.is-collapsed .pixel-progress-lamp {" in html
    assert '$pixelGenPanel.addEventListener("mouseenter", openPixelPanelTemporarily);' in html
    assert '$pixelGenPanel.addEventListener("mouseleave", maybeCollapsePixelPanel);' in html
    assert '$pixelGenPanel.addEventListener("focusin", openPixelPanelTemporarily);' in html
    assert 'const shouldOpenStarOfficeFromPanelEvent = (target) => {' in html
    assert '$pixelGenToggle.addEventListener("click", () => {' in html
    assert '$pixelGenPanel.setAttribute("aria-label", `系统状态：${resolvePixelCompactText(String(pixelGenState.status || "idle"), String(pixelGenState.stageKey || ""))}`);' in html
    assert '$pixelGenPanel.setAttribute("title", "系统状态：只读展示，不能手动暂停或恢复");' in html
    assert 'const escapePixelLogHtml = (value) => {' in html
    assert 'const safeLabelText = escapePixelLogHtml(labelText);' in html
    assert 'escapePixelLogHtml(detail)' in html
    assert 'renderPixelProgressLog(status, progress);' in html
    assert 'speechText: next.speech,' in html


def test_render_index_html_uses_smaller_blue_search_submit_button():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "width: 54px;" in html
    assert "height: 54px;" in html
    assert "background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%);" in html
    assert "width: 48px;" in html
    assert "height: 48px;" in html


def test_render_index_html_uses_orange_image_workbench_pet():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert module.HOMEPAGE_PET_ASSET_OUTPUT_NAME == "orange.png"
    assert module.HOMEPAGE_PET_ASSET_CANDIDATES[0] == module.REPO_ROOT / "assets" / "orange.png"
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
    assert 'const resp = await fetchWithTimeout(generateUrl, 12000, {' in html
    assert 'method: "POST",' in html
    assert '"X-Idempotency-Key": requestKey' in html
    assert 'const isSafeGenerateRequestKey = (value) => /^[A-Za-z0-9._:-]+$/.test(String(value || "").trim());' in html
    assert 'if (key && isSafeGenerateRequestKey(key) && createdAt > 0 && (now - createdAt) < 10 * 60 * 1000) return key;' in html
    assert 'const fresh = "storymap-" + now.toString(36) + "-" + Math.random().toString(36).slice(2, 10);' in html
    assert 'body: JSON.stringify({ person })' in html
    assert 'apiUrl("generate?person="' not in html


def test_render_index_html_polls_runtime_readiness_and_updates_search_hint():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const runtimeReadinessEnabled = !STATIC_SITE || !!resolvedApiBase;' in html
    assert 'const refreshRuntimeAvailability = async () => {' in html
    assert 'fetchWithTimeout(apiUrl("health/ready"), 8000, { cache: "no-store" });' in html
    assert 'window.setInterval(refreshRuntimeAvailability, 30000);' in html
    assert "当前可浏览但不可生成" in html
    assert "实时生成人物可用" in html


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


def test_render_index_html_omits_runtime_api_base_when_env_missing(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    monkeypatch.delenv("MAP_STORY_API_BASE", raising=False)

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "window.MAP_STORY_API_BASE=" not in html


def test_render_index_html_omits_legacy_placeholder_api_base(monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    monkeypatch.setenv("MAP_STORY_API_BASE", "http://legacy.example")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "window.MAP_STORY_API_BASE=" not in html


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
    # 搜索命中需要跨时间窗强制可见，因此隐藏分支额外排除 searchHit。
    assert "if (onlyActiveMarkers && !active && !forceVisible && !searchHit) {" in html
    assert "const emph = (active || forceVisible || (searchActive && searchHit)) && !searchDim;" in html


def test_render_index_html_shows_person_info_on_map_marker_hover():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const buildMapPersonInfoHtml = (n) => {" in html
    assert 'const birthplaceAmbiguous = /存疑|一说|或说|又说|另说|未详|不详/.test(bpRaw);' in html
    assert 'const bpDisplay = bp && birthplaceAmbiguous && showNativePlace ? "存疑" : bp;' in html
    assert 'const showNativePlace = nativePlace && (!bp || placeCompareKey(nativePlace) !== placeCompareKey(bp));' in html
    assert "if (birthplace) rows.push({ label: '出生地', value: birthplace });" in html
    assert 'if (showNativePlace) appendLine("籍贯：" + nativePlace' in html
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
    assert 'const isSpecialSunMarker = (n) => String((n && n.person) || "").trim() === "毛泽东";' in html
    assert "const sunMarkerHtml = (sz, glow, emph) => {" in html
    assert "const markerHtml = (n, sz, fill, glow, emph) => {" in html
    assert "el.innerHTML = markerHtml(n, initialSize, initialFill, initialGlow, active);" in html
    assert "if (onlyActiveMarkers && !inWindow(n)) {" in html
    assert 'el.addEventListener("mouseenter", show);' in html
    assert 'plugin=AMap.Geocoder' in html
    assert 'MarkerCluster' not in html
    assert 'const sz = dim ? 16 : (emph ? 20 : 18);' in html
    assert "it.mk.setContent(it.el);" in html
    assert 'const button = document.createElement("button");' in html
    assert 'button.addEventListener("click", () => {' in html
    assert 'openPerson(n && n.person ? n.person : "");' in html


def test_render_index_html_includes_home_work_chip_tooltip_support():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert ".home-work-chip {" in html
    assert 'id="workTip" class="home-work-tooltip hidden"' in html
    assert 'const $workTip = document.getElementById("workTip");' in html
    assert "const resolveNodeWorkSummary = (node, title) => {" in html
    assert "const buildWorkTooltipInnerHtml = (title, item) => {" in html
    assert "const showWorkTip = (title, item, clientX, clientY) => {" in html
    assert "uniqStrings(Array.isArray(item.quotes) ? item.quotes : []).length" in html
    assert 'quoteItems.map((quote) => esc(quote)).join("<br>")' in html
    assert 'const quotePolicy = String(item?.quote_policy || \'\').trim();' in html
    assert '名句展示：此类作品默认仅展示摘要' in html
    assert 'data-work-title="${esc(normalizeHomeWorkTitle(work))}"' in html
    assert 'const works = uniqStrings(Array.isArray(n.works) ? n.works : [])' in html
    assert '$searchSuggest.addEventListener("mouseover", syncSearchSuggestWorkTip);' in html
    assert 'document.addEventListener("scroll", () => hideWorkTip(), true);' in html


def test_render_index_html_opens_person_pages_in_new_tab_from_homepage():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert 'const navigateToRelativeHtml = (file, options = {}) => {' in html
    assert 'const targetUrl = "./" + encodeURIComponent(target);' in html
    assert 'const useNewTab = !!(options && options.newTab);' in html
    assert 'link.target = "_blank";' in html
    assert 'link.rel = "noopener noreferrer";' in html
    assert 'if (navigateToRelativeHtml(file, { newTab: true })) return;' in html
    assert 'const tab = window.open(resolveStarOfficeUrl(person), "_blank");' in html


def test_render_index_html_initializes_map_markers_with_dynasty_colors_and_window_visibility():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const active = inWindow(n);" in html
    assert "const base = colorByYear(n.time_year);" in html
    assert "const accent = base.startsWith(\"#\") ? hexToRgba(base, 0.92) : base;" in html
    assert "const accentSoft = base.startsWith(\"#\") ? hexToRgba(base, 0.62) : base;" in html
    assert "const initialFill = active ? accent : accentSoft;" in html
    assert "const isForeignPerson = (n) => Boolean(n && n.is_foreign);" in html
    assert "const foreignMarkerSvg = (sz, fill, glow, emph) => {" in html
    assert "const markerHtml = (n, sz, fill, glow, emph) => {" in html
    assert "el.innerHTML = markerHtml(n, initialSize, initialFill, initialGlow, active);" in html
    assert "if (onlyActiveMarkers && !inWindow(n)) {" in html
    assert "try { mk.hide(); } catch (_) {}" in html


def test_render_index_html_keeps_marker_svg_in_shared_scope_for_map_refresh():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    marker_svg_idx = html.index("const markerSvg = (sz, fill, glow, emph) => {")
    foreign_marker_idx = html.index("const foreignMarkerSvg = (sz, fill, glow, emph) => {")
    sun_marker_idx = html.index("const sunMarkerHtml = (sz, glow, emph) => {")
    init_map_idx = html.index("const initMapOnce = () => {")
    update_markers_idx = html.index("const updateMapMarkers = () => {")

    assert marker_svg_idx < init_map_idx
    assert marker_svg_idx < update_markers_idx
    assert foreign_marker_idx < init_map_idx
    assert foreign_marker_idx < update_markers_idx
    assert sun_marker_idx < init_map_idx
    assert sun_marker_idx < update_markers_idx
    assert "it.el.innerHTML = markerHtml(n, sz, fill, glow, emph);" in html
    assert "it.mk.setContent(markerHtml(n, sz, fill, glow, emph));" in html


def test_render_index_html_draws_foreign_people_as_rectangles():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const drawForeignRect = (pt, size, fillStyle, strokeStyle, lineAlpha, activeGlowAlpha) => {" in html
    assert "const foreignPerson = isForeignPerson(n);" in html
    assert "} else if (foreignPerson) {" in html
    assert "drawForeignRect(" in html
    assert "ctx.strokeRect(pt.x - size, pt.y - size, size * 2, size * 2);" in html


def test_render_index_html_uses_rectangular_city_labels_and_higher_hu_line_tag():
    module = importlib.import_module("tools.build_stellar_homepage")

    html = module._render_index_html("故事地图", "stellar_home_data.json")

    assert "const offsetDeg = 1.32;" in html
    assert 'offset: new window.AMap.Pixel(0, -5),' in html
    assert "const heihe = [127.500, 50.250];" in html
    assert 'path: [heihe, tengchong],' in html
    assert "heihe[0] + (tengchong[0] - heihe[0]) / 3" in html
    assert "heihe[1] + (tengchong[1] - heihe[1]) / 3" in html
    assert 'mkText("黑河", heihe);' in html
    assert 'mkText("腾冲", tengchong);' in html
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


def test_main_embeds_person_work_summaries_into_home_nodes(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(
        json.dumps(
            {
                "items": {
                    "苏轼": {
                        "review": "北宋文学家。",
                        "works": ["赤壁赋", "念奴娇·赤壁怀古"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(
        json.dumps(
            {
                "items": {
                    "赤壁赋": {
                        "title": "赤壁赋",
                        "authors": ["苏轼"],
                        "era": "北宋",
                        "genre": "赋",
                        "one_liner": "借赤壁夜游抒发人生感慨。",
                        "quotes": ["寄蜉蝣于天地，渺沧海之一粟。", "哀吾生之须臾，羡长江之无穷。"],
                        "quote_policy": "preferred",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (story_md_dir / "苏轼.md").write_text(
        "# 苏轼\n\n- **时代**：北宋\n- **出生**：1037年，眉州眉山\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["苏轼"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("苏轼", "苏轼", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (1037, 1101))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "北宋")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "", []))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("眉州眉山", "眉州", "四川眉山"))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("literature", "文学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "北宋")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["works"] == ["赤壁赋", "念奴娇·赤壁怀古"]
    assert node["work_summaries"]["赤壁赋"]["authors"] == ["苏轼"]
    assert node["work_summaries"]["赤壁赋"]["genre"] == "赋"
    assert node["work_summaries"]["赤壁赋"]["quote_policy"] == "preferred"
    assert node["work_summaries"]["赤壁赋"]["quotes"] == [
        "寄蜉蝣于天地，渺沧海之一粟。",
        "哀吾生之须臾，羡长江之无穷。",
    ]
    assert node["is_foreign"] is False


def test_main_allows_missing_summary_indexes(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    (story_md_dir / "苏轼.md").write_text(
        "# 苏轼\n\n- **时代**：北宋\n- **出生**：1037年，眉州眉山\n",
        encoding="utf-8",
    )
    missing_summary_index = tmp_path / "people_summary_index.json"
    missing_work_summary_index = tmp_path / "work_summary_index.json"
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(missing_summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", missing_work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["苏轼"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("苏轼", "苏轼", [])])
    monkeypatch.setattr(module, "_read_json", lambda path: json.loads(Path(path).read_text(encoding="utf-8")))
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (1037, 1101))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "北宋")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "", []))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("眉州眉山", "眉州", "四川眉山"))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("literature", "文学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "北宋")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["work_summaries"] == {}
    assert node["works"] == []


def test_main_marks_foreign_people_with_rectangular_flag(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"但丁": {"review": "意大利诗人。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "但丁.md").write_text("# 但丁\n\n- **出生**：1265年，佛罗伦萨\n", encoding="utf-8")
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["但丁"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("但丁", "但丁", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (1265, 1321))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "Dante Alighieri", []))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("佛罗伦萨", "", "意大利佛罗伦萨"))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("literature", "诗人"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["is_foreign"] is True
    assert node["foreign_name"] == "Dante Alighieri"


def test_main_keeps_chinese_people_with_foreign_name_as_non_foreign(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"徐光启": {"review": "明代科学家。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "徐光启.md").write_text("# 徐光启\n\n- **出生**：1562年，松江府上海县（今上海市）\n", encoding="utf-8")
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1800,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["徐光启"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("徐光启", "徐光启", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (1562, 1633))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "明朝")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "Paul Hsu (Xu Guangqi)", []))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("松江府上海县今上海市", "松江府上海县", "上海市"))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("science", "科学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "明朝")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["foreign_name"] == "Paul Hsu (Xu Guangqi)"
    assert node["is_foreign"] is False


def test_is_foreign_person_keeps_chinese_figures_born_abroad_as_non_foreign():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._is_foreign_person(
        foreign_name="",
        birthplace_modern="日本东京都",
        birthplace_raw="日本东京今日本东京都",
        dynasty="中国近现代（清末至中华人民共和国）",
    ) is False
    assert module._is_foreign_person(
        foreign_name="",
        birthplace_modern="日本长崎县平户市",
        birthplace_raw="日本肥前国平户今日本长崎县平户市",
        dynasty="明末清初",
    ) is False


def test_is_foreign_person_keeps_mixed_japan_tang_identity_as_foreign():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._is_foreign_person(
        foreign_name="",
        birthplace_modern="",
        birthplace_raw="日本文武天皇2年",
        dynasty="日本奈良时代、中国唐朝",
    ) is True


def test_is_foreign_person_treats_explicit_foreign_era_as_foreign():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._is_foreign_person(
        foreign_name="Matteo Ricci",
        birthplace_modern="",
        birthplace_raw="意大利马切拉塔",
        dynasty="意大利文艺复兴晚期、明代（万历年间）",
    ) is True


def test_is_foreign_person_treats_abbasid_khwarazmian_figures_as_foreign():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._is_foreign_person(
        foreign_name="Muḥammad ibn Mūsā al-Khwārizmī",
        birthplace_modern="",
        birthplace_raw="花拉子模地区",
        dynasty="阿拔斯王朝（伊斯兰黄金时代）",
    ) is True


def test_main_uses_normalized_dynasty_for_foreign_detection(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"释迦牟尼": {"review": "佛教创始人。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "释迦牟尼.md").write_text("# 释迦牟尼\n", encoding="utf-8")
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["释迦牟尼"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("释迦牟尼", "释迦牟尼", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (-563, -483))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "", []))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("", "", ""))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("thought", "宗教家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "古印度列国时代（约公元前6世纪至前5世纪）")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["dynasty"] == "古印度列国时代（约公元前6世纪至前5世纪）"
    assert node["is_foreign"] is True


def test_extract_birthplace_from_md_prefers_specific_place_over_uncertain_period_prefix():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_birthplace_from_md(
        "- **出生**：存疑，约明弘治年间，南直隶句容（今江苏省镇江市句容市）\n"
    )

    assert raw == "南直隶句容今江苏省镇江市句容市"
    assert ancient == "南直隶句容"
    assert modern == "江苏省镇江市句容市"


def test_extract_birthplace_from_md_strips_date_only_uncertainty_but_keeps_place():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_birthplace_from_md(
        "- **出生**：约公元984年，崇安（今福建省南平市武夷山市）（存疑，一说生于987年）\n"
    )

    assert raw == "崇安今福建省南平市武夷山市"
    assert ancient == "崇安"
    assert modern == "福建省南平市武夷山市"


def test_extract_birthplace_from_md_strips_parenthetical_native_place_note():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_birthplace_from_md(
        "- **出生**：1957年9月，北京（祖籍河北赵县）\n"
    )

    assert raw == "北京"
    assert ancient == "北京"
    assert modern == ""


def test_extract_birthplace_from_md_returns_empty_when_birth_field_only_declares_native_place():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_birthplace_from_md(
        "- **出生**：约公元前140年，籍贯杜陵（今陕西省西安市）\n"
    )

    assert raw == ""
    assert ancient == ""
    assert modern == ""


def test_extract_birthplace_from_md_clears_modern_place_when_birthplace_has_multiple_options():
    module = importlib.import_module("tools.build_stellar_homepage")

    raw, ancient, modern = module._extract_birthplace_from_md(
        "- **出生**：约公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）\n"
    )

    assert "雅典" in raw
    assert "埃伊纳岛" in raw
    assert ancient == "雅典"
    assert modern == ""


def test_main_prefers_markdown_coords_table_over_stale_cached_birth_coords(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"曹鎏": {"review": "明朝官员。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "曹鎏.md").write_text(
        "\n".join(
            [
                "# 曹鎏",
                "",
                "- **出生**：存疑，约明弘治年间，南直隶句容（今江苏省镇江市句容市）",
                "",
                "## 地点坐标",
                "| 现称 | 纬度 | 经度 |",
                "| --- | --- | --- |",
                "| 江苏省镇江市句容市 | 31.9440 | 119.1670 |",
            ]
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text(json.dumps({"曹鎏": [28.362776571773484, 86.69988483162376]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["曹鎏"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("曹鎏", "曹鎏", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (None, None))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "明朝（嘉靖年间）")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "", []))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("politics", "官员"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "明朝（嘉靖年间）")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["birthplace_modern"] == "江苏省镇江市句容市"
    assert node["birth_lat_wgs84"] == 31.944
    assert node["birth_lng_wgs84"] == 119.167
    assert json.loads(birth_coords_path.read_text(encoding="utf-8")) == {"曹鎏": [31.944, 119.167]}


def test_main_matches_birthplace_against_labeled_coords_table_rows(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"奥本海默": {"review": "美国理论物理学家。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "奥本海默.md").write_text(
        "\n".join(
            [
                "# 奥本海默",
                "",
                "- **出生**：公元1904年，美国纽约州纽约市",
                "",
                "## 地点坐标",
                "| 现称 | 纬度 | 经度 |",
                "| --- | --- | --- |",
                "| 出生地：纽约市 | 40.7128 | -74.0060 |",
            ]
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text(
        json.dumps({"奥本海默": [45.2968009, 130.9673405]}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["奥本海默"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("奥本海默", "奥本海默", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (1904, 1967))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "20世纪")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "", []))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("academic", "理论物理学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "20世纪")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["birth_lat_wgs84"] == 40.7128
    assert node["birth_lng_wgs84"] == -74.006
    assert json.loads(birth_coords_path.read_text(encoding="utf-8")) == {"奥本海默": [40.7128, -74.006]}


def test_main_drops_ambiguous_cached_birth_coords_when_birthplace_is_not_precise(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"欧几里得": {"review": "古希腊数学家。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "欧几里得.md").write_text("# 欧几里得\n\n- **出生**：约公元前325年，出生地存疑（说法不一，有雅典或亚历山大城等）\n", encoding="utf-8")
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text(json.dumps({"欧几里得": [30.65055060614759, 103.97938168032687]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["欧几里得"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("欧几里得", "欧几里得", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (-325, -265))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "古希腊时期（托勒密王国）")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "Euclid", ["数学", "几何学"]))
    monkeypatch.setattr(module, "_extract_birthplace_from_md", lambda md: ("有雅典或亚历山大城等", "", ""))
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("science", "数学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "古希腊时期（托勒密王国）")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["birth_lat_wgs84"] is None
    assert node["birth_lng_wgs84"] is None
    assert json.loads(birth_coords_path.read_text(encoding="utf-8")) == {}


def test_main_drops_birth_marker_when_birthplace_has_multiple_place_options(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_stellar_homepage")
    story_map_dir = tmp_path / "story_map"
    story_map_dir.mkdir()
    story_md_dir = tmp_path / "story"
    story_md_dir.mkdir()
    summary_index = tmp_path / "people_summary_index.json"
    summary_index.write_text(json.dumps({"items": {"柏拉图": {"review": "古希腊哲学家。"}}}, ensure_ascii=False), encoding="utf-8")
    work_summary_index = tmp_path / "work_summary_index.json"
    work_summary_index.write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (story_md_dir / "柏拉图.md").write_text(
        "# 柏拉图\n\n- **出生**：约公元前428/427年，雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        story_map_dir=str(story_map_dir),
        story_md_dir=str(story_md_dir),
        summary_index=str(summary_index),
        out_index="index.html",
        out_data="stellar_home_data.json",
        title="故事地图",
        default_start=100,
        default_end=1600,
        graph_source="",
    )
    captured = {}
    data_root = tmp_path / "data"
    (data_root / "validation_reports" / "strict_audit").mkdir(parents=True)
    birth_coords_path = data_root / "people_birth_coords_wgs84.json"
    birth_coords_path.write_text(json.dumps({"柏拉图": [37.9838, 23.7275]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "BIRTH_COORDS_WGS84_JSON", birth_coords_path)
    monkeypatch.setattr(module, "WORK_SUMMARY_INDEX_JSON", work_summary_index)
    monkeypatch.setattr(module, "_scan_latest_html", lambda _dir: {})
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: ["柏拉图"])
    monkeypatch.setattr(module, "_canonical_story_name_entries", lambda names: [("柏拉图", "柏拉图", [])])
    monkeypatch.setattr(
        module,
        "_read_json",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {},
    )
    monkeypatch.setattr(module, "_extract_years_from_md", lambda md: (-428, -347))
    monkeypatch.setattr(module, "_dynasty_hint_from_md", lambda md: "古希腊古典时代")
    monkeypatch.setattr(module, "_extract_relations", lambda md: ([], []))
    monkeypatch.setattr(module, "_extract_disambiguation", lambda md: ([], "Plato", ["哲学", "教育"]))
    monkeypatch.setattr(
        module,
        "_extract_birthplace_from_md",
        lambda md: ("雅典今希腊雅典或埃伊纳岛今希腊埃伊纳岛说法不一", "雅典今希腊雅典或埃伊纳岛今希腊埃伊纳岛说法不一", ""),
    )
    monkeypatch.setattr(module, "_resolve_main_role_band", lambda **kwargs: ("academic", "哲学家"))
    monkeypatch.setattr(module, "build_search_fields", lambda name, aliases, foreign_name: {"search_keys": [], "search_tokens": [], "search_pinyin": []})
    monkeypatch.setattr(module, "_normalize_dynasty_label", lambda **kwargs: "古希腊古典时代")
    monkeypatch.setattr(module, "_write_homepage_outputs", lambda **kwargs: captured.update(kwargs) or {"index": "i", "data": "d", "count": 1})

    assert module.main() == 0
    node = captured["payload"]["nodes"][0]
    assert node["birth_lat_wgs84"] is None
    assert node["birth_lng_wgs84"] is None
    assert json.loads(birth_coords_path.read_text(encoding="utf-8")) == {}


def test_remove_person_alias_redirect_pages_deletes_alias_html(tmp_path):
    module = importlib.import_module("tools.build_stellar_homepage")
    alias_path = tmp_path / "苏东坡.html"
    alias_path.write_text("redirect", encoding="utf-8")

    module._remove_person_alias_redirect_pages(tmp_path, {"苏东坡": "苏轼"})

    assert not alias_path.exists()


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


def test_normalize_dynasty_label_prefers_raw_text_over_coarse_bucket():
    module = importlib.import_module("tools.build_stellar_homepage")

    dynasty = module._normalize_dynasty_label(
        person="张飞",
        dynasty_raw="东汉末年·三国",
        birth_year=None,
        death_year=221,
    )

    assert dynasty == "东汉末年·三国"


def test_normalize_dynasty_label_falls_back_to_year_bucket_when_raw_missing():
    module = importlib.import_module("tools.build_stellar_homepage")

    dynasty = module._normalize_dynasty_label(
        person="张飞",
        dynasty_raw="",
        birth_year=None,
        death_year=221,
    )

    assert dynasty == "魏晋南北"


def test_clean_review_text_strips_short_review_prefixes():
    module = importlib.import_module("tools.build_stellar_homepage")

    assert module._clean_review_text("- 短评：浪漫主义诗歌高峰。") == "浪漫主义诗歌高峰。"
    assert module._clean_review_text("1. 人物短评: 千秋功过，后人评说。") == "千秋功过，后人评说。"
