from __future__ import annotations

import tools.build.sync_star_office_ui as module

from tools.build.sync_star_office_ui import _disable_embedded_debug_reporter

def test_disable_embedded_debug_reporter_removes_local_debug_post_target():
    html = """
        let loadingText;
        // #region debug-point A:runtime-reporter
        const ORANGE_OFFICE_DEBUG_URL = 'http://127.0.0.1:7777/event';
        const ORANGE_OFFICE_DEBUG_SESSION = 'orange-office-loading';
        function orangeOfficeDebugReport(hypothesisId, location, msg, data) {
            fetch(ORANGE_OFFICE_DEBUG_URL, { method: 'POST' }).catch(() => {});
        }
        window.addEventListener('error', () => orangeOfficeDebugReport('A', 'window:error', 'x', {}));
        // #endregion
        function boot() {}
    """

    sanitized = _disable_embedded_debug_reporter(html)

    assert "127.0.0.1:7777/event" not in sanitized
    assert "fetch(ORANGE_OFFICE_DEBUG_URL" not in sanitized
    assert "window.addEventListener('error'" not in sanitized
    assert "function orangeOfficeDebugReport() {}" in sanitized
    assert "function boot() {}" in sanitized

def test_sync_star_office_ui_writes_into_requested_target_dir(tmp_path, monkeypatch):
    frontend_dir = tmp_path / "frontend"
    assets_dir = frontend_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "desk.txt").write_text("desk", encoding="utf-8")
    (frontend_dir / "index.html").write_text(
        """
        <html>
          <head>
            <title>Star 的像素办公室</title>
            <style></style>
          </head>
          <body>
            <div id="loading-overlay">
                <div id="loading-text">Loading Orange’s pixel office...</div>
                <div id="loading-progress-container">
                    <div id="loading-progress-bar"></div>
                </div>
            </div>
            // #region debug-point A:runtime-reporter
            const ORANGE_OFFICE_DEBUG_URL = 'http://127.0.0.1:7777/event';
            function orangeOfficeDebugReport(hypothesisId, location, msg, data) {
                fetch(ORANGE_OFFICE_DEBUG_URL, { method: 'POST' }).catch(() => {});
            }
            // #endregion
        </body>
        </html>
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "STAR_OFFICE_FRONTEND", frontend_dir)
    target_dir = tmp_path / "out"

    module.sync_star_office_ui(target_dir)

    html = (target_dir / "orange-office.html").read_text(encoding="utf-8")
    assert "http://127.0.0.1:7777/event" not in html
    assert "function orangeOfficeDebugReport() {}" in html
    assert "storymap-gen-progress-bar" in html
    assert "storymap-gen-steps" in html
    assert "agent_status" in html
    assert "normalizedAgentStatus" in html
    assert "识别人物" in html
    assert "定位地点" in html
    assert "质量检查" in html
    assert (target_dir / "static" / "assets" / "desk.txt").read_text(encoding="utf-8") == "desk"
