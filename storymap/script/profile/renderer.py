import hashlib
import json
import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

from ..core.analytics import analytics_head_html
from ..core.build_meta import build_artifact_meta
from ..core.env_utils import _first_env, apply_story_map_env_aliases, env_flag
from ..core.person_registry import person_redirects
from ..core.project_paths import project_root_path, story_artifacts_dir_path, story_md_dir_path, story_person_names
from .graph_service import (
    build_home_graph_file_fallback,
    get_related_people_graph,
    get_related_people_graph_from_payload,
    get_related_people_graph_from_sqlite,
    home_graph_person_names,
    invalidate_graph_service_cache,
    load_home_graph_payload,
)
from .map_bootstrap_js import amap_bootstrap_js, map_bootstrap_js
from .tooltip_js import person_tooltip_js


apply_story_map_env_aliases()


_TEMPLATE_DIR = Path(__file__).resolve().with_name("templates")
_REPO_ROOT = project_root_path()
STELLAR_HOME_DATA_JSON = story_artifacts_dir_path() / "stellar_home_data.json"


@lru_cache(maxsize=None)
def _load_html_template(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _design_tokens_css() -> str:
    return (_TEMPLATE_DIR / "design_tokens.css").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def profile_render_dependency_paths(root: Optional[Path] = None) -> tuple[Path, ...]:
    base_root = Path(root or _REPO_ROOT).resolve()
    return (
        Path(__file__).resolve(),
        base_root / "storymap" / "script" / "core" / "parsers.py",
        base_root / "storymap" / "script" / "core" / "person_registry.py",
        base_root / "storymap" / "script" / "profile" / "map_bootstrap_js.py",
        base_root / "storymap" / "script" / "profile" / "tooltip_js.py",
        base_root / "storymap" / "script" / "profile" / "graph_service.py",
        base_root / "storymap" / "script" / "profile" / "builder.py",
        base_root / "storymap" / "script" / "profile" / "profile_builder.py",
        _TEMPLATE_DIR / "profile_page.html",
        _TEMPLATE_DIR / "design_tokens.css",
        base_root / "storymap" / "script" / "story_map.py",
        base_root / "cli" / "generate_pure_story_map.py",
    )


@lru_cache(maxsize=1)
def profile_template_signature() -> str:
    sha1 = hashlib.sha1()
    for path in profile_render_dependency_paths():
        if path.exists():
            sha1.update(path.read_bytes())
    return sha1.hexdigest()[:12]


def _render_html_template(
    template: str,
    *,
    title: str,
    data: str,
    runtime_config: str,
    site_mode_notice: str,
    amap_bootstrap: str,
    analytics_head: str,
) -> str:
    artifact_meta = build_artifact_meta(component="profile_page")
    tpl_sig = profile_template_signature()
    return (
        template.replace("__TITLE__", title)
        .replace("__DATA__", data)
        .replace("__DESIGN_TOKENS__", '<link rel="stylesheet" href="./static/design-tokens.css">')
        .replace("__PERSON_TOOLTIP_JS__", person_tooltip_js())
        .replace("__RUNTIME_CONFIG__", runtime_config)
        .replace("__SITE_MODE_NOTICE__", site_mode_notice)
        .replace("__AMAP_BOOTSTRAP__", amap_bootstrap)
        .replace("__ANALYTICS_HEAD__", analytics_head)
        .replace("__BUILD_VERSION__", str(artifact_meta.get("build_version") or ""))
        .replace("__BUILD_AT__", str(artifact_meta.get("build_at") or ""))
        .replace("__BUILD_SOURCE_COMMIT__", str(artifact_meta.get("source_commit") or ""))
        .replace("__BUILD_COMPONENT__", str(artifact_meta.get("artifact_component") or ""))
        .replace("__TPL_SIG__", tpl_sig)
    )


_PROFILE_BABEL_SCRIPT_RE = re.compile(
    r'<script\s+type="text/babel"\s+data-presets="env,react">\s*(.*?)\s*</script>',
    re.S,
)


@lru_cache(maxsize=1)
def _compiled_profile_app_js() -> str:
    template = _load_html_template("profile_page.html")
    match = _PROFILE_BABEL_SCRIPT_RE.search(template)
    if not match:
        raise RuntimeError("profile_page.html missing text/babel app script")
    source = str(match.group(1) or "").strip()
    if not source:
        raise RuntimeError("profile_page.html text/babel app script is empty")
    # 将数据初始化保留在 HTML 层面（不编译到外部 JS），避免 __DATA__ 占位符无法替换
    source = source.replace("const data = __DATA__;", "")
    source = source.replace("window.__EXPORT_DATA__ = data;", "")
    # __PERSON_TOOLTIP_JS__ 占位符在 Babel 脚本块内，需在编译前替换为实际 JS
    try:
        source = source.replace("__PERSON_TOOLTIP_JS__", person_tooltip_js())
    except Exception:
        pass
    vendor_babel = _REPO_ROOT / "artifacts" / "story_map" / "vendor" / "babel.min.js"
    if not vendor_babel.exists():
        raise RuntimeError(f"missing Babel runtime for build-time compilation: {vendor_babel}")
    node_script = f"""
const fs = require('fs');
const Babel = require({json.dumps(str(vendor_babel))});
const source = fs.readFileSync(0, 'utf8');
const result = Babel.transform(source, {{
  presets: ['react'],
  comments: false,
  minified: false,
  compact: false,
}});
process.stdout.write(String((result && result.code) || ''));
""".strip()
    proc = subprocess.run(
        ["node", "-e", node_script],
        input=source,
        text=True,
        capture_output=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"build-time Babel transform failed: {proc.stderr.strip() or proc.stdout.strip()}")
    compiled = str(proc.stdout or "").strip()
    if not compiled:
        raise RuntimeError("build-time Babel transform returned empty output")
    return compiled


def _build_tailwind_css() -> None:
    """使用 Tailwind v4 CLI 从模板中提取 class 名，生成构建时压缩 CSS。

    替代了原先在浏览器中加载 tailwindcss.js 运行时编译的方案，
    将 CSS 体积从 398KB JS 降低为约 60KB 静态 CSS 文件。
    """
    static_dir = story_artifacts_dir_path() / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    input_css = _TEMPLATE_DIR / "tailwind-input.css"
    output_css = static_dir / "tailwind.css"
    profile_template = _TEMPLATE_DIR / "profile_page.html"
    landing_html = story_artifacts_dir_path() / "landing.html"
    content_paths = [profile_template]
    if landing_html.exists():
        content_paths.append(landing_html)
    try:
        import shutil
        npx = shutil.which("npx") or "/opt/homebrew/bin/npx"
        cmd = [
            npx, "tailwindcss",
            "-i", str(input_css),
            "-o", str(output_css),
            "--minify",
        ]
        for cp in content_paths:
            cmd.extend(["--content", str(cp)])
        subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        _LOGGER.warning("Tailwind CSS build skipped: %s", exc)


def _write_profile_static_assets() -> None:
    """将编译后的 React App JS、design_tokens.css 与 tailwind.css 写入共享静态目录。

    所有人物页共用这些文件（而非每个 HTML 内联一份副本）。UI 改
    动时仅需重新编译写入这几个文件，无需渲染任何人物页。
    """
    static_dir = story_artifacts_dir_path() / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    js_path = static_dir / "profile-app.js"
    css_path = static_dir / "design-tokens.css"
    try:
        compiled_js = _compiled_profile_app_js()
    except (FileNotFoundError, RuntimeError, OSError, subprocess.SubprocessError):
        return
    js_path.write_text(compiled_js, encoding="utf-8")
    css_path.write_text(_design_tokens_css(), encoding="utf-8")
    _build_tailwind_css()
    # 复制 Service Worker 到 artifacts 根目录
    sw_src = _REPO_ROOT / "vendor" / "sw.js"
    sw_dst = story_artifacts_dir_path() / "sw.js"
    if sw_src.exists():
        try:
            sw_dst.write_text(sw_src.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass


@lru_cache(maxsize=1)
def _compiled_profile_template() -> str:
    raw_template = _load_html_template("profile_page.html")
    try:
        _write_profile_static_assets()
    except (FileNotFoundError, RuntimeError, OSError, subprocess.SubprocessError):
        return raw_template

    # 将构建时编译的 Tailwind CSS 链接插入模板（替代已删除的 tailwindcss.js 运行时）
    template = raw_template.replace(
        '<!-- tailwind.css is built-time compiled; see scripts section in package.json -->',
        '<link rel="stylesheet" href="./static/tailwind.css">',
    )
    template = template.replace('<link rel="preload" href="./vendor/babel.min.js" as="script" crossorigin="anonymous">', '')
    template = template.replace('<script src="./vendor/babel.min.js"></script>\n', "")
    # 静态资源指纹化：追加 ?v=SIG 确保浏览器不会缓存旧版本
    tpl_sig = profile_template_signature()
    cache_bust = f"?v={tpl_sig}"[:16]  # template sig 取前 8 字符即可
    # 数据初始化保留在 HTML 中（__DATA__ 占位符由 _render_html_template 替换）
    script_tag = f'<script>const data = __DATA__; window.__EXPORT_DATA__ = data;</script>\n<script src="./static/profile-app.js{cache_bust}"></script>\n'
    template, count = _PROFILE_BABEL_SCRIPT_RE.subn(lambda _m: script_tag, template, count=1)
    if count != 1:
        return raw_template
    # 也给 CSS 文件加指纹
    template = template.replace(
        '<link rel="stylesheet" href="./static/tailwind.css">',
        f'<link rel="stylesheet" href="./static/tailwind.css{cache_bust}">',
    )
    template = template.replace(
        './static/design-tokens.css',
        f'./static/design-tokens.css{cache_bust}',
    )
    return template


def _runtime_api_base_env() -> str:
    api_base = _first_env("MAP_STORY_API_BASE")
    if "legacy.example" in api_base.lower():
        return ""
    # 避免把开发用 / loopback 地址硬编码进静态页面：浏览器在用户机器上
    # 访问 ECS / OpenDeploy 公网域名时，如果 API_BASE 是 127.0.0.1 / localhost，
    # 前端 fetch 会全部回到用户本地的 8765，永远连不到真实后端。
    # 这种情况让前端用相对路径（同源探测）才是正确行为。
    lowered = api_base.lower()
    if lowered.startswith("http://127.0.0.1") or lowered.startswith("http://localhost") or lowered.startswith("https://localhost"):
        return ""
    if lowered.startswith("http://[::1]") or lowered.startswith("https://[::1]"):
        return ""
    return api_base


def _runtime_debug_config() -> Dict[str, str]:
    if not env_flag("MAP_STORY_ENABLE_RUNTIME_DEBUG_CONFIG", "STORY_MAP_ENABLE_RUNTIME_DEBUG_CONFIG"):
        return {}
    result: Dict[str, str] = {}
    session_name = _first_env("MAP_STORY_RUNTIME_DEBUG_SESSION", "STORY_MAP_RUNTIME_DEBUG_SESSION")
    dbg_name = f"{session_name}.env" if session_name else "map-loading-blank.env"
    dbg_env = _REPO_ROOT / ".dbg" / dbg_name
    if not dbg_env.exists():
        return result
    try:
        for raw_line in dbg_env.read_text(encoding="utf-8").splitlines():
            line = str(raw_line or "").strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = str(key or "").strip()
            value = str(value or "").strip()
            if key == "DEBUG_SERVER_URL":
                result["server"] = value
            elif key == "DEBUG_SESSION_ID":
                result["session"] = value
    except Exception:
        return {}
    return result


def _runtime_page_config_html() -> str:
    static_site = env_flag("MAP_STORY_STATIC_SITE", "GITHUB_PAGES_STATIC")
    api_base = _runtime_api_base_env()
    ai_endpoint = _first_env("MAP_STORY_AI_ENDPOINT")
    parts = [f"window.MAP_STORY_STATIC_SITE={'true' if static_site else 'false'};"]
    debug_cfg = _runtime_debug_config()
    if api_base:
        parts.append(f"window.MAP_STORY_API_BASE={json.dumps(api_base, ensure_ascii=False)};")
    if ai_endpoint:
        parts.append(f"window.MAP_STORY_AI_ENDPOINT={json.dumps(ai_endpoint, ensure_ascii=False)};")
    if debug_cfg.get("server"):
        parts.append(f"window.__STORY_MAP_DEBUG_SERVER__={json.dumps(debug_cfg['server'], ensure_ascii=False)};")
    if debug_cfg.get("session"):
        parts.append(f"window.__STORY_MAP_DEBUG_SESSION_ID__={json.dumps(debug_cfg['session'], ensure_ascii=False)};")
    return "<script>" + "".join(parts) + "</script>"


def _site_mode_notice_html() -> str:
    static_site = env_flag("MAP_STORY_STATIC_SITE", "GITHUB_PAGES_STATIC")
    api_base = _first_env("MAP_STORY_API_BASE")
    if not static_site:
        return ""
    detail = "已接入外部后端，可继续使用实时生成与人物对话。" if api_base else "当前仅展示已生成内容；人物对话与实时生成需要额外部署 FastAPI 后端。"
    return f"""
<div id="site-mode-notice" class="max-w-screen-2xl mx-auto mb-4 rounded-xl border border-amber-200/80 bg-amber-50/90 px-4 py-3 shadow-sm">
  <div class="flex items-start justify-between gap-3 flex-wrap">
    <div>
      <div class="text-sm font-semibold text-amber-900">静态演示版</div>
      <div class="text-[11px] text-amber-800/90 mt-1">{detail}</div>
    </div>
    <div class="text-[11px] font-semibold text-amber-700">Pages</div>
  </div>
</div>
<script>
(() => {{
  try {{
    const host = String(window.location?.hostname || '').trim().toLowerCase();
    const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');
    const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);
    const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith('.local');
    if (!isDevHost) return;
    const notice = document.getElementById('site-mode-notice');
    if (notice) notice.style.display = 'none';
  }} catch (_) {{}}
}})();
</script>"""


def _amap_bootstrap_html() -> str:
    """高德地图 AMap 运行时脚本加载器（含 <script> 标签）。

    JS 实现位于 map_bootstrap_js.py，便于独立维护与 lint。
    """
    return f"<script>\n{amap_bootstrap_js()}\n</script>"


def _profile_map_bootstrap_html() -> str:
    """MapLibre / Cesium / GeoVis 运行时引导 JS（含 <script> 标签）。

    JS 实现位于 map_bootstrap_js.py，便于独立维护与 lint。
    """
    return f"<script>\n{map_bootstrap_js()}\n</script>"


def invalidate_stellar_home_data_cache() -> None:
    """清除首页图谱渲染缓存。首页数据变更后调用。"""
    _load_stellar_home_data.cache_clear()
    _build_stellar_home_fallback.cache_clear()
    invalidate_graph_service_cache()


@lru_cache(maxsize=1)
def _load_stellar_home_data() -> Dict[str, Any]:
    return load_home_graph_payload(STELLAR_HOME_DATA_JSON)


@lru_cache(maxsize=1)
def _build_stellar_home_fallback() -> Dict[str, Any]:
    return build_home_graph_file_fallback()


def _build_related_people_graph(data: Dict[str, Any], limit: int = 6) -> Dict[str, Any]:
    person = data.get("person") if isinstance(data.get("person"), dict) else {}
    person_name = str(person.get("name") or "").strip()
    if not person_name:
        return {"center": {}, "nodes": [], "links": []}

    # 1. 优先 SQLite（结构化数据库，人工维护的关系）
    try:
        graph_result = get_related_people_graph_from_sqlite(person_name, limit=limit)
    except Exception as exc:
        _LOGGER.debug("SQLite graph fallback failed for %r: %s", person_name, exc)
        graph_result = {}
    if isinstance(graph_result, dict) and isinstance(graph_result.get("nodes"), list) and graph_result.get("nodes"):
        return graph_result

    # 2. 尝试 Neo4j（如果配置了）
    markdown = str(data.get("markdown") or "")
    try:
        graph_result = get_related_people_graph(person, markdown=markdown, limit=limit)
    except Exception as exc:
        _LOGGER.debug("Neo4j graph fallback failed for %r: %s", person_name, exc)
        graph_result = {}
    if isinstance(graph_result, dict) and isinstance(graph_result.get("nodes"), list) and graph_result.get("nodes"):
        return graph_result

    # 3. 回退到 JSON payload（Markdown 语义提取 + 课本同册推理）
    payload = _load_stellar_home_data()
    return get_related_people_graph_from_payload(person, payload, markdown=markdown, limit=limit)


def build_info_panel_html(_title: str, fields: Dict[str, str]) -> str:
    """构建基础地图页左上角的信息面板。"""
    order = ["朝代", "身份", "生卒年", "主要事件", "主要作品", "历史地位", "一生行程"]
    wrap = ['<div class="bio-panel"><div class="bio-body">']
    for k in order:
        val = fields.get(k, "")
        if val:
            esc = val.replace("<", "&lt;").replace(">", "&gt;")
            wrap.append(f'<div class="bio-row"><span class="bio-label">{k}：</span>{esc}</div>')
    wrap.append("</div></div>")
    css = """
<style>
.bio-panel{position:fixed;top:12px;left:12px;z-index:9999;max-width:380px;background:#ffffffee;padding:12px 14px;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.15);font:14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial;}
.bio-panel h3{margin:0 0 8px 0;font-size:16px;}
.bio-row{margin:4px 0;}
.bio-label{color:#666;margin-right:4px;}
</style>
"""
    return css + "".join(wrap)


def render_profile_html(data: Dict[str, object]) -> str:
    """
    渲染完整人物页（头像 + 统计卡片 + 足迹时间轴 + 地图）。
    """
    payload_dict = dict(data)
    if not payload_dict.get("relatedGraph"):
        payload_dict["relatedGraph"] = _build_related_people_graph(payload_dict)
    try:
        story_names = story_person_names(story_md_dir_path())
    except Exception:
        story_names = []
    payload_dict["personRedirects"] = person_redirects(story_names)
    # 注入全量人物名列表，供聊天 @ 提及使用
    try:
        payload_dict["allPeopleNames"] = home_graph_person_names()
    except Exception:
        payload_dict["allPeopleNames"] = []
    payload_dict["templateSignature"] = profile_template_signature()
    payload_dict["artifactMeta"] = build_artifact_meta(component="profile_page")
    payload = json.dumps(payload_dict, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    name = (payload_dict.get("person", {}) or {}).get("name", "")
    title = f"{name}的人生足迹地图" if name else "人生足迹地图"
    runtime_config = _runtime_page_config_html()
    site_mode_notice = _site_mode_notice_html()
    amap_bootstrap = _amap_bootstrap_html() + _profile_map_bootstrap_html()
    analytics_head = analytics_head_html(page_type="profile", page_name=str(name or ""))
    return _render_html_template(
        _compiled_profile_template(),
        title=title,
        data=payload.replace("</script>", "<\\/script>"),
        runtime_config=runtime_config,
        site_mode_notice=site_mode_notice,
        amap_bootstrap=amap_bootstrap,
        analytics_head=analytics_head,
    )


def render_multi_html(data: Dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = data.get("title") or "多人物合并视图"
    runtime_config = _runtime_page_config_html()
    site_mode_notice = _site_mode_notice_html()
    amap_bootstrap = _amap_bootstrap_html()
    analytics_head = analytics_head_html(page_type="multi_profile", page_name=str(title or ""))
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<link rel="stylesheet" href="./static/tailwind.css">
__RUNTIME_CONFIG__
__AMAP_BOOTSTRAP__
__ANALYTICS_HEAD__
<style>
body{font-family:'Noto Serif SC',serif;background-color:#fdf6e3;color:#2c3e50;}
#map{height:80vh;width:100%;border-radius:12px;box-shadow:0 6px 12px rgba(0,0,0,0.12);}
.legend{position:fixed;left:16px;top:16px;background:rgba(255,255,255,0.9);border:1px solid rgba(200,180,150,0.5);border-radius:10px;padding:10px 12px;z-index:9999;}
.legend-item{display:flex;align-items:center;gap:8px;font-size:12px;margin-top:6px;}
.legend-color{width:10px;height:10px;border-radius:999px;}
</style>
</head>
<body class="p-4 md:p-8">
__SITE_MODE_NOTICE__
<div id="legend" class="legend"></div>
<div id="map"></div>
<script>
const data = __DATA__;
window.__EXPORT_DATA__ = data;
const people = data.people || [];
const legend = document.getElementById('legend');
const overlap = data.overlaps || [];
const overlapText = overlap.length ? overlap.map(o => o.name).join('、') : '暂无';
legend.innerHTML = `<div class="text-sm font-semibold">人物轨迹</div>` + people.map(p => `
  <div class="legend-item">
    <span class="legend-color" style="background:${p.color || '#1e40af'}"></span>
    <span>${p.person?.name || ''}</span>
  </div>
`).join('') + `<div class="text-[11px] text-slate-500 mt-2">交集地点：${overlapText}</div>`;
const initMap = async () => {
  await _ensureAmap();
  const map = new AMap.Map('map', {
    zoom: 4,
    center: [105, 35],
    viewMode: '2D',
    resizeEnable: true
  });
  const overlays = [];
  const infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -18) });
  people.forEach((p) => {
    const color = p.color || '#1e40af';
    const locations = p.locations || [];
    const line = locations.map((loc) => [loc.lng, loc.lat]);
    if (line.length > 1) {
      const polyline = new AMap.Polyline({
        path: line,
        strokeColor: color,
        strokeWeight: 4,
        strokeOpacity: 0.75,
        lineJoin: 'round',
        lineCap: 'round'
      });
      map.add(polyline);
      overlays.push(polyline);
    }
    locations.forEach((loc) => {
      const marker = new AMap.CircleMarker({
        center: [loc.lng, loc.lat],
        radius: 8,
        strokeColor: color,
        strokeWeight: 2,
        fillColor: color,
        fillOpacity: 0.35,
        bubble: true
      });
      marker.on('click', () => {
        infoWindow.setContent(`<div style="font-size:12px;line-height:1.5;"><strong>${p.person?.name || ''}</strong><br/>${loc.name || ''}</div>`);
        infoWindow.open(map, [loc.lng, loc.lat]);
      });
      map.add(marker);
      overlays.push(marker);
    });
  });
  if (overlays.length > 0) {
    try {
      map.setFitView(overlays);
    } catch (_) {}
  }
};
initMap().catch((err) => {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:16px;top:16px;z-index:9999;background:rgba(255,255,255,0.94);padding:10px 12px;border-radius:10px;border:1px solid rgba(0,0,0,0.08);font-size:12px;color:#7c2d12;';
  box.textContent = `高德地图加载失败：${String(err?.message || err)}`;
  document.body.appendChild(box);
});
</script>
</body>
</html>"""
    return (
        html.replace("__TITLE__", title)
        .replace("__DATA__", payload.replace("</script>", "<\\/script>"))
        .replace("__RUNTIME_CONFIG__", runtime_config)
        .replace("__SITE_MODE_NOTICE__", site_mode_notice)
        .replace("__AMAP_BOOTSTRAP__", amap_bootstrap)
        .replace("__ANALYTICS_HEAD__", analytics_head)
    )


def render_amap_html(title: str, points: List[Dict[str, object]], info_panel_html: str = "") -> str:
    """
    渲染基础高德地图页（点位与连线）。
    """
    center = {"lat": 35.0, "lon": 105.0, "zoom": 4}
    if points:
        lat = float(points[0]["lat"])
        lon = float(points[0]["lon"])
        center = {"lat": lat, "lon": lon, "zoom": 6}
    pts_json = json.dumps(points, ensure_ascii=False)
    runtime_config = _runtime_page_config_html()
    amap_bootstrap = _amap_bootstrap_html()
    analytics_head = analytics_head_html(page_type="amap_profile", page_name=str(title or ""))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title} - 生平地图</title>
{runtime_config}
{amap_bootstrap}
{analytics_head}
<style>html,body,#map{{height:100%;margin:0;padding:0}}</style>
</head>
<body>
<div id="map"></div>
{info_panel_html}
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
const pts = {pts_json};
const initMap = async () => {{
  await _ensureAmap();
  const map = new AMap.Map('map', {{
    zoom: {center["zoom"]},
    center: [{center["lon"]}, {center["lat"]}],
    viewMode: '2D',
    resizeEnable: true
  }});
  const overlays = [];
  const latlngs = pts.map((p) => [p.lon, p.lat]);
  const infoWindow = new AMap.InfoWindow({{ offset: new AMap.Pixel(0, -18) }});
  if (latlngs.length > 1) {{
    const polyline = new AMap.Polyline({{
      path: latlngs,
      strokeColor: '#555',
      strokeWeight: 3,
      strokeOpacity: 0.75,
      lineJoin: 'round',
      lineCap: 'round'
    }});
    map.add(polyline);
    overlays.push(polyline);
  }}
  pts.forEach((p, i) => {{
    let style = {{radius: 7, strokeColor: '#3498db', fillColor: '#3498db', fillOpacity: 0.9, strokeWeight: 2, bubble: true}};
    if (i === 0) style = {{radius: 8, strokeColor: '#2ecc71', fillColor: '#2ecc71', fillOpacity: 1.0, strokeWeight: 2, bubble: true}};
    if (i === pts.length - 1) style = {{radius: 8, strokeColor: '#e74c3c', fillColor: '#e74c3c', fillOpacity: 1.0, strokeWeight: 2, bubble: true}};
    const marker = new AMap.CircleMarker(Object.assign({{ center: [p.lon, p.lat] }}, style));
    marker.on('click', () => {{
      infoWindow.setContent(marked.parse(p.md || ''));
      infoWindow.open(map, [p.lon, p.lat]);
    }});
    map.add(marker);
    overlays.push(marker);
  }});
  if (overlays.length > 0) {{
    try {{
      map.setFitView(overlays);
    }} catch (_) {{}}
  }}
}};
initMap().catch((err) => {{
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:16px;top:16px;z-index:9999;background:rgba(255,255,255,0.94);padding:10px 12px;border-radius:10px;border:1px solid rgba(0,0,0,0.08);font-size:12px;color:#7c2d12;';
  box.textContent = `高德地图加载失败：${{String(err?.message || err)}}`;
  document.body.appendChild(box);
}});
</script>
</body>
</html>"""
    return html
