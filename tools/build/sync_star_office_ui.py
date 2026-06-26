from __future__ import annotations

import re
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STAR_OFFICE_FRONTEND = REPO_ROOT / ".tmp_star_office_ui" / "frontend"
TARGET_DIR = REPO_ROOT / "artifacts" / "story_map"

SKIP_FILES = {
    "index.html",
    "invite.html",
    "join.html",
    "electron-standalone.html",
    "join-office-skill.md",
    "office-agent-push.py",
}

STYLE_OVERRIDE = """
        #control-bar { display: none !important; }
        #guest-agent-panel { display: none !important; }
        #bottom-panels { width: min(1280px, 100vw); justify-content: center; margin-top: 14px; }
        #main-stage { width: min(1280px, 100vw); }
        #game-container { width: min(1280px, 100vw); height: auto; aspect-ratio: 1280 / 720; }
        body { padding: 0; background: #111827; }
        #storymap-gen-banner {
            position: fixed;
            top: 16px;
            right: 16px;
            z-index: 999999;
            width: min(420px, calc(100vw - 24px));
            padding: 14px 16px;
            border-radius: 14px;
            border: 1px solid rgba(251, 191, 36, 0.28);
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.96), rgba(15, 23, 42, 0.92));
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.32);
            color: #f9fafb;
            pointer-events: none;
        }
        #storymap-gen-banner[hidden] { display: none !important; }
        #storymap-gen-banner[data-status="completed"] {
            border-color: rgba(74, 222, 128, 0.34);
        }
        #storymap-gen-banner[data-status="failed"],
        #storymap-gen-banner[data-status="partial_failed"] {
            border-color: rgba(248, 113, 113, 0.38);
        }
        #storymap-gen-banner-title {
            font-size: 15px;
            font-weight: 700;
            line-height: 1.4;
            color: #fff7ed;
        }
        #storymap-gen-banner-desc {
            margin-top: 6px;
            font-size: 12px;
            line-height: 1.6;
            color: rgba(255,255,255,0.8);
        }
        #storymap-gen-banner-meta {
            margin-top: 10px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 4px 8px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            font-size: 11px;
            color: rgba(255,255,255,0.74);
        }
"""

GENERATION_BANNER_HTML = """
    <div id="storymap-gen-banner" hidden data-status="queued" aria-live="polite">
        <div id="storymap-gen-banner-title">正在生成人物页…</div>
        <div id="storymap-gen-banner-desc">已进入 Orange Office，正在准备生成进度。</div>
        <div id="storymap-gen-banner-meta">任务进度同步中</div>
    </div>
"""

GENERATION_BANNER_SCRIPT = """
    <script>
    (function () {
        const params = new URLSearchParams(window.location.search);
        const person = (params.get('person') || '').trim();
        const taskId = (params.get('task') || '').trim();
        const banner = document.getElementById('storymap-gen-banner');
        const titleEl = document.getElementById('storymap-gen-banner-title');
        const descEl = document.getElementById('storymap-gen-banner-desc');
        const metaEl = document.getElementById('storymap-gen-banner-meta');
        if (!banner || (!person && !taskId)) return;

        const defaultTitle = person ? `正在生成「${person}」的人物页…` : '正在生成人物页…';
        banner.hidden = false;

        function render(status, detail, meta) {
            const normalized = String(status || 'queued').trim() || 'queued';
            banner.dataset.status = normalized;
            if (titleEl) titleEl.textContent = defaultTitle;
            if (descEl) descEl.textContent = detail || '已进入 Orange Office，正在同步生成进度。';
            if (metaEl) metaEl.textContent = meta || '任务进度同步中';
            try {
                document.title = person ? `${person} 生成中 - Orange Office` : '人物生成中 - Orange Office';
            } catch (_) {}
        }

        function labelForStatus(status) {
            switch (status) {
                case 'queued': return '排队中';
                case 'running': return '生成中';
                case 'completed': return '已完成';
                case 'partial_failed': return '部分完成';
                case 'failed': return '生成失败';
                default: return status || '进行中';
            }
        }

        function detailFromSnapshot(snapshot) {
            const progress = Array.isArray(snapshot && snapshot.progress) ? snapshot.progress : [];
            const last = progress.length ? progress[progress.length - 1] : null;
            const label = last && last.label ? String(last.label).trim() : '';
            const detail = last && last.detail ? String(last.detail).trim() : '';
            if (label && detail) return `${label}：${detail}`;
            if (detail) return detail;
            if (label) return label;
            const queue = snapshot && snapshot.queue ? snapshot.queue : {};
            const pos = queue && queue.position ? String(queue.position) : '';
            const limit = queue && queue.limit ? String(queue.limit) : '';
            if ((snapshot && snapshot.status) === 'queued' && pos && limit) return `当前排队 ${pos}/${limit}`;
            return '';
        }

        if (!taskId) {
            render('queued', '已进入 Orange Office，正在等待生成任务启动。', '任务尚未分配');
            return;
        }

        let stopped = false;
        async function pollTask() {
            if (stopped) return;
            try {
                const response = await fetch('/task?id=' + encodeURIComponent(taskId), { cache: 'no-store' });
                const snapshot = await response.json();
                if (!snapshot || snapshot.exists !== true) {
                    render('queued', '已进入 Orange Office，正在等待任务进入队列。', '任务创建中');
                    setTimeout(pollTask, 1200);
                    return;
                }
                const status = String(snapshot.status || '').trim() || 'queued';
                const detail = detailFromSnapshot(snapshot);
                const meta = taskId ? `${labelForStatus(status)} · 任务 ${taskId.slice(0, 8)}` : labelForStatus(status);
                if (status === 'completed') {
                    render(status, detail || '人物页已生成，正在自动跳转到对应页面。', meta);
                    stopped = true;
                    return;
                }
                if (status === 'failed' || status === 'partial_failed') {
                    render(status, detail || '任务结束，但未完全成功。', meta);
                    stopped = true;
                    return;
                }
                render(status, detail || 'Orange Office 正在同步当前生成进度。', meta);
            } catch (_) {
                render('queued', '进度同步稍有延迟，正在自动重试。', '任务进度同步中');
            }
            if (!stopped) setTimeout(pollTask, 1200);
        }

        render('queued', '已进入 Orange Office，正在同步当前生成进度。', taskId ? `任务 ${taskId.slice(0, 8)}` : '任务进度同步中');
        pollTask();
    })();
    </script>
"""

INTERNAL_AGENT_FILTER_SCRIPT = """
        function isHiddenInternalAgent(agent) {
            const agentId = String(agent && agent.agentId || '').trim().toLowerCase();
            const name = String(agent && agent.name || '').trim();
            if (!agentId && !name) return false;
            if (['site-guard', 'recover-agent', 'sync-agent', 'archive-agent', 'publish-agent', 'front-desk'].includes(agentId)) {
                return true;
            }
            return /前台|接待|档案|整理|发布/.test(name);
        }
        function filterVisibleGuestAgents(list) {
            return (Array.isArray(list) ? list : []).filter(agent => !isHiddenInternalAgent(agent));
        }
"""


def _disable_embedded_debug_reporter(html: str) -> str:
    text = str(html or "")
    pattern = re.compile(
        r"\s*// #region debug-point A:runtime-reporter[\s\S]*?// #endregion\s*",
        flags=re.MULTILINE,
    )
    replacement = """
        function orangeOfficeDebugReport() {}

"""
    return pattern.sub(replacement, text, count=1)


def _resolve_target_dir(target_dir: Path | None = None) -> Path:
    if target_dir is None:
        return TARGET_DIR
    return Path(target_dir)


def sync_star_office_ui(target_dir: Path | None = None) -> None:
    if not STAR_OFFICE_FRONTEND.exists():
        raise FileNotFoundError(f"missing source frontend: {STAR_OFFICE_FRONTEND}")

    resolved_target_dir = _resolve_target_dir(target_dir)
    target_static_dir = resolved_target_dir / "static"
    target_html = resolved_target_dir / "orange-office.html"

    target_static_dir.mkdir(parents=True, exist_ok=True)
    for item in STAR_OFFICE_FRONTEND.iterdir():
        if item.name in SKIP_FILES:
            continue
        target = target_static_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    html = (STAR_OFFICE_FRONTEND / "index.html").read_text(encoding="utf-8")
    html = _disable_embedded_debug_reporter(html)
    html = html.replace("<title>Star 的像素办公室</title>", "<title>橙子科技公司</title>")
    html = html.replace(
        """            #lang-btn-en,
            #lang-btn-jp,
            #lang-btn-cn {""",
        """            #lang-btn-en,
            #lang-btn-cn {""",
    )
    html = html.replace(
        """        <button id="lang-btn-en" onclick="setUILanguage('en')" style="padding:8px 10px; font-family:ArkPixel,monospace; font-size:13px; cursor:pointer; border:2px solid #333; border-radius:5px; background:#333; color:#fff;">EN</button>
        <button id="lang-btn-jp" onclick="setUILanguage('ja')" style="padding:8px 10px; font-family:ArkPixel,monospace; font-size:13px; cursor:pointer; border:2px solid #333; border-radius:5px; background:#333; color:#fff;">JP</button>
        <button id="lang-btn-cn" onclick="setUILanguage('zh')" style="padding:8px 10px; font-family:ArkPixel,monospace; font-size:13px; cursor:pointer; border:2px solid #333; border-radius:5px; background:#333; color:#fff;">CN</button>""",
        """        <button id="lang-btn-en" onclick="setUILanguage('en')" style="padding:8px 10px; font-family:ArkPixel,monospace; font-size:13px; cursor:pointer; border:2px solid #333; border-radius:5px; background:#333; color:#fff;">EN</button>
        <button id="lang-btn-cn" onclick="setUILanguage('zh')" style="padding:8px 10px; font-family:ArkPixel,monospace; font-size:13px; cursor:pointer; border:2px solid #333; border-radius:5px; background:#333; color:#fff;">CN</button>""",
    )
    html = html.replace(
        """            const langButtons = [
                { id: 'lang-btn-en', lang: 'en' },
                { id: 'lang-btn-jp', lang: 'ja' },
                { id: 'lang-btn-cn', lang: 'zh' }
            ];""",
        """            const langButtons = [
                { id: 'lang-btn-en', lang: 'en' },
                { id: 'lang-btn-cn', lang: 'zh' }
            ];""",
    )
    html = html.replace("</style>", STYLE_OVERRIDE + "\n    </style>", 1)
    html = html.replace(
        "        function fetchGuestAgents() {\n",
        INTERNAL_AGENT_FILTER_SCRIPT + "\n        function fetchGuestAgents() {\n",
        1,
    )
    html = html.replace(
        "                    guestAgents = Array.isArray(data) ? data : [];",
        "                    guestAgents = filterVisibleGuestAgents(Array.isArray(data) ? data : []);",
        1,
    )
    html = html.replace(
        """    <div id="loading-overlay">
        <div id="loading-text">Loading Orange’s pixel office...</div>
        <div id="loading-progress-container">
            <div id="loading-progress-bar"></div>
        </div>
    </div>
    """,
        """    <div id="loading-overlay">
        <div id="loading-text">Loading Orange’s pixel office...</div>
        <div id="loading-progress-container">
            <div id="loading-progress-bar"></div>
        </div>
    </div>
""" + GENERATION_BANNER_HTML + """
    """,
        1,
    )
    html = html.replace("</body>", GENERATION_BANNER_SCRIPT + "\n</body>", 1)
    target_html.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    sync_star_office_ui()
