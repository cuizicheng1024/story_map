import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .env_utils import apply_story_map_env_aliases, env_flag
    from .graph_service import (
        build_home_graph_file_fallback,
        get_related_people_graph,
        get_related_people_graph_from_payload,
        invalidate_graph_service_cache,
        load_home_graph_payload,
    )
    from .person_registry import person_redirects
    from .person_tooltip_js import person_tooltip_js
    from .project_paths import project_root_path, story_artifacts_dir_path, story_md_dir_path, story_person_names
except ImportError:
    from env_utils import apply_story_map_env_aliases, env_flag
    from graph_service import (
        build_home_graph_file_fallback,
        get_related_people_graph,
        get_related_people_graph_from_payload,
        invalidate_graph_service_cache,
        load_home_graph_payload,
    )
    from person_registry import person_redirects
    from person_tooltip_js import person_tooltip_js
    from project_paths import project_root_path, story_artifacts_dir_path, story_md_dir_path, story_person_names


apply_story_map_env_aliases()


_TEMPLATE_DIR = Path(__file__).resolve().with_name("templates")
_REPO_ROOT = project_root_path()
_DEFAULT_GA_MEASUREMENT_ID = "G-74J5L22QGX"
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
        base_root / "storymap" / "script" / "parsers.py",
        base_root / "storymap" / "script" / "person_registry.py",
        base_root / "storymap" / "script" / "person_tooltip_js.py",
        base_root / "storymap" / "script" / "graph_service.py",
        base_root / "storymap" / "script" / "profile_builder.py",
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
    return (
        template.replace("__TITLE__", title)
        .replace("__DATA__", data)
        .replace("__DESIGN_TOKENS__", f"<style>\n{_design_tokens_css()}\n</style>")
        .replace("__PERSON_TOOLTIP_JS__", person_tooltip_js())
        .replace("__RUNTIME_CONFIG__", runtime_config)
        .replace("__SITE_MODE_NOTICE__", site_mode_notice)
        .replace("__AMAP_BOOTSTRAP__", amap_bootstrap)
        .replace("__ANALYTICS_HEAD__", analytics_head)
    )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _analytics_head_html() -> str:
    measurement_id = _first_env("MAP_STORY_GA_MEASUREMENT_ID", "GA_MEASUREMENT_ID") or _DEFAULT_GA_MEASUREMENT_ID
    if not measurement_id:
        return ""
    quoted_id = json.dumps(measurement_id, ensure_ascii=False)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>'
        "<script>"
        "window.dataLayer=window.dataLayer||[];"
        "function gtag(){dataLayer.push(arguments);}"
        "gtag('js', new Date());"
        f"gtag('config', {quoted_id});"
        "</script>"
    )


def _runtime_page_config_html() -> str:
    static_site = env_flag("MAP_STORY_STATIC_SITE", "GITHUB_PAGES_STATIC")
    api_base = _first_env("MAP_STORY_API_BASE")
    ai_endpoint = _first_env("MAP_STORY_AI_ENDPOINT")
    parts = [f"window.MAP_STORY_STATIC_SITE={'true' if static_site else 'false'};"]
    if api_base:
        parts.append(f"window.MAP_STORY_API_BASE={json.dumps(api_base, ensure_ascii=False)};")
    if ai_endpoint:
        parts.append(f"window.MAP_STORY_AI_ENDPOINT={json.dumps(ai_endpoint, ensure_ascii=False)};")
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
    key = _first_env("AMAP_KEY")
    security = _first_env("AMAP_SECURITY")
    parts: List[str] = []
    if key:
        parts.append(f"window.AMAP_KEY={json.dumps(key, ensure_ascii=False)};")
    if security:
        parts.append(f"window.AMAP_SECURITY={json.dumps(security, ensure_ascii=False)};")
    inline = f"<script>{''.join(parts)}</script>" if parts else ""
    loader = """<script>
(() => {
  try {
    const host = String(window.location?.hostname || '').trim().toLowerCase();
    const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');
    const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);
    const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith('.local');
    if (window.location && window.location.protocol !== 'file:' && !window.__MAP_STORY_AMAP_CONFIG__ && (window.MAP_STORY_STATIC_SITE !== true || isDevHost)) {
      window.__MAP_STORY_AMAP_CONFIG__ = true;
      const cfg = document.createElement('script');
      cfg.src = new URL('./amap-config.js', window.location.href).toString();
      cfg.async = false;
      document.head.appendChild(cfg);
    }
  } catch (_) {}
})();
let amapLoading = false;
const _getAmapKey = () => {
  let k = '';
  try {
    k = (new URLSearchParams(window.location.search).get('amapKey') || '').trim();
  } catch (_) {}
  if (!k) k = String(window.AMAP_KEY || '').trim();
  try {
    if (!k) k = String(localStorage.getItem('AMAP_KEY') || '').trim();
  } catch (_) {}
  return k;
};
const _getAmapSecurity = () => {
  let s = '';
  try {
    s = (new URLSearchParams(window.location.search).get('amapSec') || '').trim();
  } catch (_) {}
  if (!s) s = String(window.AMAP_SECURITY || '').trim();
  try {
    if (!s) s = String(localStorage.getItem('AMAP_SECURITY') || '').trim();
  } catch (_) {}
  return s;
};
const _ensureAmap = () => new Promise((resolve, reject) => {
  if (window.AMap && typeof window.AMap.Map === 'function') return resolve(true);
  const key = _getAmapKey();
  if (!key) return reject(new Error('AMAP_KEY_REQUIRED'));
  const sec = _getAmapSecurity();
  if (sec) {
    window._AMapSecurityConfig = { securityJsCode: sec };
  }
  if (amapLoading) {
    const t0 = Date.now();
    const tick = () => {
      if (window.AMap && typeof window.AMap.Map === 'function') return resolve(true);
      if (Date.now() - t0 > 12000) return reject(new Error('AMAP_LOAD_TIMEOUT'));
      setTimeout(tick, 80);
    };
    return tick();
  }
  amapLoading = true;
  const sEl = document.createElement('script');
  sEl.async = true;
  sEl.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&plugin=AMap.TileLayer.Satellite,AMap.TerrainLayer`;
  sEl.onload = () => {
    amapLoading = false;
    if (window.AMap && typeof window.AMap.Map === 'function') resolve(true);
    else reject(new Error('AMAP_LOAD_FAILED'));
  };
  sEl.onerror = () => {
    amapLoading = false;
    reject(new Error('AMAP_LOAD_FAILED'));
  };
  document.head.appendChild(sEl);
});
</script>"""
    return inline + loader


def _profile_map_bootstrap_html() -> str:
    loader = """<script>
(() => {
  try {
    const host = String(window.location?.hostname || '').trim().toLowerCase();
    const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');
    const isPrivateIPv4 = /^(10\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[0-1])\\.)/.test(host);
    const isDevHost = isLocalHost || isPrivateIPv4 || host.endsWith('.local');
    if (window.location && window.location.protocol !== 'file:' && !window.__MAP_STORY_GEOVIS_CONFIG__ && (window.MAP_STORY_STATIC_SITE !== true || isDevHost)) {
      window.__MAP_STORY_GEOVIS_CONFIG__ = true;
      const cfg = document.createElement('script');
      cfg.src = new URL('./geovis-config.js', window.location.href).toString();
      cfg.async = false;
      document.head.appendChild(cfg);
    }
  } catch (_) {}
})();
let mapLibreLoading = false;
let cesiumLoading = false;
const _getGeoVisToken = () => {
  let token = '';
  try {
    token = (new URLSearchParams(window.location.search).get('geovisToken') || '').trim();
  } catch (_) {}
  if (!token) token = String(window.GEOVIS_TOKEN || '').trim();
  try {
    if (!token) token = String(localStorage.getItem('GEOVIS_TOKEN') || localStorage.getItem('DATACLOUD_TOKEN') || '').trim();
  } catch (_) {}
  return token;
};
const _appendCss = (href) => {
  if (!href) return;
  const key = `link[data-runtime-href="${href}"]`;
  if (document.querySelector(key)) return;
  const el = document.createElement('link');
  el.rel = 'stylesheet';
  el.href = href;
  el.setAttribute('data-runtime-href', href);
  document.head.appendChild(el);
};
const _appendScript = (src) => {
  if (!src || document.querySelector(`script[data-runtime-src="${src}"]`)) return null;
  const el = document.createElement('script');
  el.async = true;
  el.src = src;
  el.setAttribute('data-runtime-src', src);
  document.head.appendChild(el);
  return el;
};
const _ensureMapLibre = () => new Promise((resolve, reject) => {
  if (window.maplibregl && typeof window.maplibregl.Map === 'function') return resolve(true);
  const cssHref = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';
  const jsSrc = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
  _appendCss(cssHref);
  if (mapLibreLoading) {
    const t0 = Date.now();
    const tick = () => {
      if (window.maplibregl && typeof window.maplibregl.Map === 'function') return resolve(true);
      if (Date.now() - t0 > 12000) return reject(new Error('MAPLIBRE_LOAD_TIMEOUT'));
      setTimeout(tick, 80);
    };
    return tick();
  }
  mapLibreLoading = true;
  const sEl = _appendScript(jsSrc) || document.querySelector(`script[data-runtime-src="${jsSrc}"]`);
  sEl.onload = () => {
    mapLibreLoading = false;
    if (window.maplibregl && typeof window.maplibregl.Map === 'function') resolve(true);
    else reject(new Error('MAPLIBRE_LOAD_FAILED'));
  };
  sEl.onerror = () => {
    mapLibreLoading = false;
    reject(new Error('MAPLIBRE_LOAD_FAILED'));
  };
});
const _ensureCesium = () => new Promise((resolve, reject) => {
  if (window.Cesium && typeof window.Cesium.Viewer === 'function') return resolve(true);
  const cssHref = 'https://cdn.jsdelivr.net/npm/cesium@1.124.0/Build/Cesium/Widgets/widgets.css';
  const jsSrc = 'https://cdn.jsdelivr.net/npm/cesium@1.124.0/Build/Cesium/Cesium.js';
  _appendCss(cssHref);
  try {
    if (!window.CESIUM_BASE_URL) {
      window.CESIUM_BASE_URL = 'https://cdn.jsdelivr.net/npm/cesium@1.124.0/Build/Cesium/';
    }
  } catch (_) {}
  if (cesiumLoading) {
    const t0 = Date.now();
    const tick = () => {
      if (window.Cesium && typeof window.Cesium.Viewer === 'function') return resolve(true);
      if (Date.now() - t0 > 16000) return reject(new Error('CESIUM_LOAD_TIMEOUT'));
      setTimeout(tick, 100);
    };
    return tick();
  }
  cesiumLoading = true;
  const sEl = _appendScript(jsSrc) || document.querySelector(`script[data-runtime-src="${jsSrc}"]`);
  sEl.onload = () => {
    cesiumLoading = false;
    if (window.Cesium && typeof window.Cesium.Viewer === 'function') resolve(true);
    else reject(new Error('CESIUM_LOAD_FAILED'));
  };
  sEl.onerror = () => {
    cesiumLoading = false;
    reject(new Error('CESIUM_LOAD_FAILED'));
  };
});
const _geoVisTileUrl = (kind, format) => {
  const token = _getGeoVisToken();
  if (!token) throw new Error('GEOVIS_TOKEN_REQUIRED');
  const fmt = encodeURIComponent(format || 'png');
  return `https://tiles1.geovisearth.com/base/v1/${kind}/{z}/{x}/{y}?format=${fmt}&tmsIds=w&token=${encodeURIComponent(token)}`;
};
const _geoVisTerrainServiceUrl = () => {
  const token = _getGeoVisToken();
  if (!token) throw new Error('GEOVIS_TOKEN_REQUIRED');
  return `https://tiles1.geovisearth.com/base/v1/terrain/layer.json?token=${encodeURIComponent(token)}`;
};
const _geoVisTerrainRootUrl = () => {
  const token = _getGeoVisToken();
  if (!token) throw new Error('GEOVIS_TOKEN_REQUIRED');
  return `https://tiles1.geovisearth.com/base/v1/terrain/?token=${encodeURIComponent(token)}`;
};
const _probeGeoVisTile = (kind, format) => new Promise((resolve, reject) => {
  let url = '';
  try {
    url = _geoVisTileUrl(kind || 'vec', format || 'png')
      .replace('{z}', '0')
      .replace('{x}', '0')
      .replace('{y}', '0');
  } catch (err) {
    return reject(err);
  }
  const img = new Image();
  let settled = false;
  const done = (ok, err) => {
    if (settled) return;
    settled = true;
    try { img.onload = null; img.onerror = null; } catch (_) {}
    if (ok) resolve(true);
    else reject(err || new Error('GEOVIS_TILE_PROBE_FAILED'));
  };
  const timer = setTimeout(() => done(false, new Error('GEOVIS_TILE_PROBE_TIMEOUT')), 6000);
  img.onload = () => {
    clearTimeout(timer);
    done(true);
  };
  img.onerror = () => {
    clearTimeout(timer);
    done(false, new Error('GEOVIS_TILE_PROBE_FAILED'));
  };
  img.referrerPolicy = 'no-referrer';
  img.src = url;
});
const _buildGeoVisMapLibreStyle = (layerType) => {
  const mode = String(layerType || 'vector') === 'terrain-3d' ? 'vector' : String(layerType || 'vector');
  const sources = {};
  const layers = [];
  const pushRaster = (id, kind, format, opacity) => {
    sources[id] = {
      type: 'raster',
      tiles: [_geoVisTileUrl(kind, format)],
      tileSize: 256
    };
    layers.push({
      id,
      type: 'raster',
      source: id,
      paint: typeof opacity === 'number' ? { 'raster-opacity': opacity } : {}
    });
  };
  pushRaster('geovis-vec', 'vec', 'png');
  pushRaster('geovis-img', 'img', 'webp');
  pushRaster('geovis-cia', 'cia', 'png');
  pushRaster('geovis-ter', 'ter', 'png');
  pushRaster('geovis-cat', 'cat', 'png');
  layers.forEach((layer) => {
    const id = String(layer.id || '');
    const visible = (
      (mode === 'vector' && id === 'geovis-vec') ||
      (mode === 'imagery' && (id === 'geovis-img' || id === 'geovis-cia')) ||
      (mode === 'terrain' && (id === 'geovis-ter' || id === 'geovis-cat'))
    );
    layer.layout = { visibility: visible ? 'visible' : 'none' };
  });
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources,
    layers
  };
};
const _applyGeoVisMapLibreMode = (map, layerType) => {
  if (!map || typeof map.setLayoutProperty !== 'function') return;
  const mode = String(layerType || 'vector') === 'terrain-3d' ? 'vector' : String(layerType || 'vector');
  const visibleIds = new Set(
    mode === 'imagery'
      ? ['geovis-img', 'geovis-cia']
      : mode === 'terrain'
        ? ['geovis-ter', 'geovis-cat']
        : ['geovis-vec']
  );
  ['geovis-vec', 'geovis-img', 'geovis-cia', 'geovis-ter', 'geovis-cat'].forEach((id) => {
    try {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, 'visibility', visibleIds.has(id) ? 'visible' : 'none');
      }
    } catch (_) {}
  });
};
window.__MAP_STORY_GEOVIS__ = {
  getToken: _getGeoVisToken,
  tileUrl: _geoVisTileUrl,
  terrainServiceUrl: _geoVisTerrainServiceUrl,
  terrainRootUrl: _geoVisTerrainRootUrl,
  probeTile: _probeGeoVisTile,
  ensureMapLibre: _ensureMapLibre,
  ensureCesium: _ensureCesium,
  buildMapLibreStyle: _buildGeoVisMapLibreStyle,
  applyMapLibreMode: _applyGeoVisMapLibreMode
};
</script>"""
    return loader


REPO_ROOT = Path(__file__).resolve().parents[2]
def invalidate_stellar_home_data_cache() -> None:
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

    markdown = str(data.get("markdown") or "")
    try:
        graph_result = get_related_people_graph(person, markdown=markdown, limit=limit)
    except Exception:
        graph_result = {}
    if isinstance(graph_result, dict) and isinstance(graph_result.get("nodes"), list) and graph_result.get("nodes"):
        return graph_result

    payload = _load_stellar_home_data()
    return get_related_people_graph_from_payload(person, payload, markdown=markdown, limit=limit)


def build_info_panel_html(_title: str, fields: Dict[str, str]) -> str:

    """
    构建基础地图页左上角的信息面板。
    """
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
    payload_dict["templateSignature"] = profile_template_signature()
    payload = json.dumps(payload_dict, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    name = (payload_dict.get("person", {}) or {}).get("name", "")
    title = f"{name}的人生足迹地图" if name else "人生足迹地图"
    runtime_config = _runtime_page_config_html()
    site_mode_notice = _site_mode_notice_html()
    amap_bootstrap = _amap_bootstrap_html() + _profile_map_bootstrap_html()
    analytics_head = _analytics_head_html()
    return _render_html_template(
        _load_html_template("profile_page.html"),
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
    analytics_head = _analytics_head_html()
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<script src="./vendor/tailwindcss.js"></script>
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
    analytics_head = _analytics_head_html()
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
