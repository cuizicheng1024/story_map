import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from .env_utils import apply_story_map_env_aliases, env_flag
    from .person_registry import canonical_person_name, person_redirects
    from .person_tooltip_js import person_tooltip_js
    from .project_paths import project_root_path, story_artifacts_dir_path, story_md_dir_path, story_person_names
except ImportError:
    from env_utils import apply_story_map_env_aliases, env_flag
    from person_registry import canonical_person_name, person_redirects
    from person_tooltip_js import person_tooltip_js
    from project_paths import project_root_path, story_artifacts_dir_path, story_md_dir_path, story_person_names


apply_story_map_env_aliases()


_TEMPLATE_DIR = Path(__file__).resolve().with_name("templates")
_REPO_ROOT = project_root_path()
_DEFAULT_GA_MEASUREMENT_ID = "G-74J5L22QGX"
_PEOPLE_MASTER_JSON = _REPO_ROOT / "data" / "people_master.json"
_KNOWLEDGE_GRAPH_JSON = _REPO_ROOT / "data" / "people_knowledge_graph.json"


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
    if (!isLocalHost) return;
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
    if (window.location && window.location.protocol !== 'file:' && !window.__MAP_STORY_AMAP_CONFIG__ && (window.MAP_STORY_STATIC_SITE !== true || isLocalHost)) {
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
    if (window.location && window.location.protocol !== 'file:' && !window.__MAP_STORY_GEOVIS_CONFIG__ && (window.MAP_STORY_STATIC_SITE !== true || isLocalHost)) {
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
STELLAR_HOME_DATA_JSON = story_artifacts_dir_path() / "stellar_home_data.json"


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        m = re.search(r"(公元前|前)?\s*(-?\d{1,4})\s*年?", text)
        if m:
            num = int(m.group(2))
            if m.group(1):
                return -abs(num)
            return num
        m2 = re.search(r"-?\d{1,4}", text)
        if m2:
            return int(m2.group(0))
    except Exception:
        return None
    return None


def _normalize_dynasty(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    for sep in ("（", "("):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    for suffix in ("时期", "时代", "王朝"):
        s = s.replace(suffix, "")
    return s.strip()


def _same_dynasty(a: Any, b: Any) -> bool:
    sa = _normalize_dynasty(a)
    sb = _normalize_dynasty(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    if sa in sb or sb in sa:
        return True
    return len(sa) >= 2 and len(sb) >= 2 and sa[:2] == sb[:2]


def _pick_year_range(person: Dict[str, Any], node: Optional[Dict[str, Any]] = None) -> tuple[Optional[int], Optional[int]]:
    node = node or {}
    birth = _to_int(((person.get("birth") or {}) if isinstance(person.get("birth"), dict) else {}).get("date"))
    death = _to_int(((person.get("death") or {}) if isinstance(person.get("death"), dict) else {}).get("date"))
    if birth is None:
        birth = _to_int(node.get("birth_year"))
    if death is None:
        death = _to_int(node.get("death_year"))
    if birth is None:
        birth = _to_int(node.get("time_year"))
    if death is None and birth is not None:
        life_raw = str(person.get("lifespan") or "").strip()
        life_years = _to_int(life_raw)
        if life_years and 0 < life_years < 130:
            death = birth + life_years
    return birth, death


@lru_cache(maxsize=1)
def _load_stellar_home_data() -> Dict[str, Any]:
    try:
        if STELLAR_HOME_DATA_JSON.exists():
            payload = json.loads(STELLAR_HOME_DATA_JSON.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list):
                return payload
    except Exception:
        pass
    return _build_stellar_home_fallback()


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _build_stellar_home_fallback() -> Dict[str, Any]:
    master = _read_json_file(_PEOPLE_MASTER_JSON)
    people = master.get("people") if isinstance(master.get("people"), list) else []
    nodes: List[Dict[str, Any]] = []
    person_to_idx: Dict[str, int] = {}
    for item in people:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("has_story")):
            continue
        name = str(item.get("person") or "").strip()
        if not name or name in person_to_idx:
            continue
        person_to_idx[name] = len(nodes)
        nodes.append(
            {
                "person": name,
                "file": f"{name}.html",
                "dynasty": str(item.get("dynasty") or "").strip(),
                "birth_year": item.get("birth_year"),
                "death_year": item.get("death_year"),
                "aliases": [],
                "domain_tags": [],
            }
        )

    raw_graph = _read_json_file(_KNOWLEDGE_GRAPH_JSON)
    raw_edges = raw_graph.get("edges") if isinstance(raw_graph.get("edges"), list) else []
    edges: List[Dict[str, Any]] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        a = person_to_idx.get(source)
        b = person_to_idx.get(target)
        if a is None or b is None:
            continue
        edge_type = str(item.get("type") or "").strip().lower()
        try:
            weight = int(item.get("weight") or 0)
        except Exception:
            weight = 0
        if edge_type not in {"manual", "same_book"} or weight < 2:
            continue
        if edge_type == "manual":
            label = "人工关系"
            confidence = 0.9
        else:
            label = "同册共现"
            confidence = max(0.15, min(0.60, 0.15 + 0.07 * max(0, weight - 2)))
        edges.append(
            {
                "a": a,
                "b": b,
                "type": edge_type,
                "label": label,
                "confidence": confidence,
                "weight": weight,
            }
        )
    return {"nodes": nodes, "edges": edges}


def invalidate_stellar_home_data_cache() -> None:
    _load_stellar_home_data.cache_clear()
    _build_stellar_home_fallback.cache_clear()


def _extract_markdown_title(markdown: str) -> str:
    text = str(markdown or "")
    m = re.search(r"^\s*#\s+([^\n#]+)", text, flags=re.MULTILINE)
    return str(m.group(1) or "").strip() if m else ""


def _normalize_person_token(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    s = re.sub(r"[（(].*?[）)]", "", s).strip()
    s = re.sub(r"[《》【】\[\]<>\"“”‘’·•\s]+", "", s)
    return s.strip()


def _canonical_person_name(value: Any, available_names: Optional[Iterable[str]] = None) -> str:
    return canonical_person_name(value, available_names=available_names)


def _collect_node_aliases(node: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    alias_noise = re.compile(r"存疑|待考|说法不一|史料|一说|本名|原名|今译|误作|未详")

    def push(value: Any, *, primary: bool = False) -> None:
        raw = str(value or "").strip()
        if not raw:
            return
        norm = _normalize_person_token(raw)
        if len(norm) < 2 or norm in seen:
            return
        if alias_noise.search(norm):
            return
        if not primary and len(norm) < 3:
            return
        seen.add(norm)
        # 展示层要保留原始字形；这里只用归一化结果做去重，避免把中点、
        # 连字符等真实姓名样式压平成检索 token。
        out.append(raw)

    push(node.get("person"), primary=True)
    for item in node.get("aliases") or []:
        push(item)
    return out


def _guess_relation_label(context: str) -> str:
    text = str(context or "")
    if re.search(r"禅位|禅让|受禅|代汉", text):
        return "禅让"
    if re.search(r"父亲|母亲|兄长|弟弟|姐姐|妹妹|儿子|女儿|宗亲|皇叔|叔父|叔侄|兄弟|姐妹", text):
        return "宗亲"
    if re.search(r"师从|师事|老师|导师|弟子|门生|从学", text):
        return "师生"
    if re.search(r"好友|友人|朋友|结交|交游|唱和|酬答|相会", text):
        return "好友"
    if re.search(r"并称|齐名", text):
        return "并称"
    if re.search(r"拥立|废.*立|立.*为帝|挟天子|奉天子|迎.*至|迎.*都|控制|挟持|辅佐|主公|君臣|幕僚|部下|麾下|丞相", text):
        return "君臣"
    if re.search(r"政敌|对手|征讨|讨伐|反对|攻打|兵败|作乱", text):
        return "对手"
    return "人物关联"


def _extract_markdown_relation_candidates(
    markdown: str,
    alias_to_idx: Dict[str, int],
    nodes: List[Dict[str, Any]],
    current_aliases: List[str],
) -> List[tuple[float, str, Dict[str, Any], Optional[float]]]:
    text = str(markdown or "")
    if not text:
        return []

    current_set = {_normalize_person_token(x) for x in current_aliases if _normalize_person_token(x)}
    hits: Dict[int, Dict[str, Any]] = {}
    alias_items = sorted(alias_to_idx.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, idx in alias_items:
        norm_alias = _normalize_person_token(alias)
        if not norm_alias or norm_alias in current_set:
            continue
        start = 0
        while True:
            pos = text.find(alias, start)
            if pos < 0:
                break
            start = pos + len(alias)
            prefix = text[max(0, pos - 8):pos]
            suffix = text[pos + len(alias):min(len(text), pos + len(alias) + 12)]
            lo = max(0, pos - 10)
            hi = min(len(text), pos + len(alias) + 10)
            context = text[lo:hi]
            item = hits.get(idx)
            label = "人物关联"
            suppress_sentence = False
            if re.search(r"禅位于|禅让给|受禅于", prefix) or re.search(r"^(受禅|代汉|继位)", suffix):
                label = "禅让"
            elif "去世后" in suffix and "禅位" in suffix:
                suppress_sentence = True
            elif re.search(r"关系密切|联系紧密|交往密切|往来密切|来往密切", prefix + suffix + context):
                label = "相关人物"
            elif re.search(r"迎|挟持|控制|辅佐|拥立|废|立|奉天子|挟天子", prefix + suffix):
                label = "君臣"
            else:
                label = _guess_relation_label(context)
            used_sentence = False
            if label == "人物关联" and not suppress_sentence:
                left = max(text.rfind("。", 0, pos), text.rfind("\n", 0, pos), text.rfind("！", 0, pos), text.rfind("？", 0, pos))
                right_candidates = [x for x in [text.find("。", pos), text.find("\n", pos), text.find("！", pos), text.find("？", pos)] if x >= 0]
                right = min(right_candidates) if right_candidates else len(text)
                sentence = text[(left + 1) if left >= 0 else 0:right]
                label = _guess_relation_label(sentence)
                used_sentence = label != "人物关联"
            if label == "人物关联":
                continue
            score = 88.0
            if label == "禅让":
                score = 99.0
            elif label == "君臣":
                score = 97.0
            elif label == "宗亲":
                score = 96.0
            elif label == "师生":
                score = 95.0
            elif label == "好友":
                score = 94.0
            elif label == "并称":
                score = 93.0
            elif label == "对手":
                score = 92.0
            if used_sentence:
                score = min(score, 91.0)
            if item is None or score > float(item.get("score") or 0):
                hits[idx] = {"score": score, "label": label}
    out: List[tuple[float, str, Dict[str, Any], Optional[float]]] = []
    for idx, meta in hits.items():
        if 0 <= idx < len(nodes):
            out.append((float(meta["score"]), str(meta["label"]), nodes[idx], None))
    out.sort(key=lambda item: (item[0], str(item[2].get("person") or "")), reverse=True)
    return out


def _build_related_people_graph(data: Dict[str, Any], limit: int = 6) -> Dict[str, Any]:
    person = data.get("person") if isinstance(data.get("person"), dict) else {}
    person_name = str(person.get("name") or "").strip()
    if not person_name:
        return {"center": {}, "nodes": [], "links": []}

    payload = _load_stellar_home_data()
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []

    markdown = str(data.get("markdown") or "")
    display_name = _extract_markdown_title(markdown) or person_name
    current_aliases = [x for x in [person_name, display_name] if str(x or "").strip()]

    nodes: List[Dict[str, Any]] = []
    person_to_idx: Dict[str, int] = {}
    alias_to_idx: Dict[str, int] = {}
    normalized_alias_to_idx: Dict[str, int] = {}
    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["_idx"] = idx
        name = str(item.get("person") or "").strip()
        if name:
            person_to_idx[name] = idx
        for alias in _collect_node_aliases(item):
            alias_to_idx.setdefault(alias, idx)
            normalized = _normalize_person_token(alias)
            if normalized:
                normalized_alias_to_idx.setdefault(normalized, idx)
        nodes.append(item)
    available_person_names = [str(node.get("person") or "").strip() for node in nodes if str(node.get("person") or "").strip()]

    adjacency: Dict[int, List[tuple[int, Dict[str, Any]]]] = {}
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        try:
            a = int(raw.get("a"))
            b = int(raw.get("b"))
        except Exception:
            continue
        if a < 0 or b < 0 or a == b or a >= len(nodes) or b >= len(nodes):
            continue
        adjacency.setdefault(a, []).append((b, raw))
        adjacency.setdefault(b, []).append((a, raw))

    current_idx = None
    for alias in current_aliases:
        normalized = _normalize_person_token(alias)
        current_idx = normalized_alias_to_idx.get(normalized)
        if current_idx is None:
            current_idx = person_to_idx.get(str(alias).strip())
        if current_idx is not None:
            break
    if current_idx is None:
        current_idx = person_to_idx.get(person_name)
    if current_idx is None and display_name:
        current_idx = person_to_idx.get(display_name)
    current_node = nodes[current_idx] if current_idx is not None else {}
    current_dynasty = str(person.get("dynasty") or current_node.get("dynasty") or "").strip()
    current_birth, current_death = _pick_year_range(person, current_node)
    current_tags = {
        str(x).strip()
        for x in (current_node.get("domain_tags") if isinstance(current_node.get("domain_tags"), list) else [])
        if str(x).strip()
    }

    selected: List[Dict[str, Any]] = []
    seen_names = {person_name, display_name, str(current_node.get("person") or "").strip()}
    seen_canonical_names = {
        canonical
        for canonical in (_canonical_person_name(name, available_person_names) for name in seen_names)
        if canonical
    }

    def add_candidate(node: Dict[str, Any], relation_label: str, score: float, source_type: str, confidence: Optional[float] = None) -> None:
        name = str(node.get("person") or "").strip()
        canonical_name = _canonical_person_name(name, available_person_names)
        if not name or name in seen_names or (canonical_name and canonical_name in seen_canonical_names):
            return
        file_name = str(node.get("file") or f"{name}.html").strip()
        aliases = [x for x in _collect_node_aliases(node) if str(x or "").strip() and str(x).strip() != name][:4]
        selected.append(
            {
                "id": name,
                "name": name,
                "file": file_name,
                "dynasty": str(node.get("dynasty") or "").strip(),
                "aliases": aliases,
                "birth_year": _to_int(node.get("birth_year")),
                "death_year": _to_int(node.get("death_year")),
                "quote": str(node.get("quote") or "").strip(),
                "review": str(node.get("review") or "").strip(),
                "foreign_name": str(node.get("foreign_name") or "").strip(),
                "main_role_label": str(node.get("main_role_label") or "").strip(),
                "birthplace": str(node.get("birthplace") or "").strip(),
                "birthplace_modern": str(node.get("birthplace_modern") or "").strip(),
                "domain_tags": [str(x).strip() for x in (node.get("domain_tags") if isinstance(node.get("domain_tags"), list) else []) if str(x).strip()][:4],
                "has_story": bool(node.get("has_story", True)),
                "relationLabel": str(relation_label or "相关人物").strip() or "相关人物",
                "sourceType": source_type,
                "confidence": round(float(confidence), 2) if confidence is not None else None,
                "_score": float(score),
            }
        )
        seen_names.add(name)
        if canonical_name:
            seen_canonical_names.add(canonical_name)

    if current_idx is not None:
        explicit_edges = sorted(
            adjacency.get(current_idx, []),
            key=lambda item: (
                float(item[1].get("confidence") or 0),
                float(item[1].get("weight") or 0),
                str(nodes[item[0]].get("person") or ""),
            ),
            reverse=True,
        )
        deferred_same_book_edges: List[tuple[int, Dict[str, Any]]] = []
        for other_idx, edge in explicit_edges:
            other = nodes[other_idx]
            label = str(edge.get("label") or "相关人物").strip() or "相关人物"
            edge_type = str(edge.get("type") or "graph").strip()
            try:
                confidence = float(edge.get("confidence"))
            except Exception:
                confidence = None
            if edge_type == "same_book":
                # “同册共现”只是弱信号，先暂存起来，避免把正文里明确提到的人物
                # 或更高置信的人物边挤出有限名额。
                deferred_same_book_edges.append((other_idx, edge))
                continue
            base_score = 100.0
            if edge_type == "manual":
                base_score = 104.0
            score = base_score + (confidence or 0.0) * 10.0
            try:
                score += float(edge.get("weight") or 0)
            except Exception:
                pass
            add_candidate(other, label, score, edge_type, confidence)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        for score, label, node, confidence in _extract_markdown_relation_candidates(markdown, alias_to_idx, nodes, current_aliases):
            add_candidate(node, label, score, "markdown", confidence)
            if len(selected) >= limit:
                break

    if current_idx is not None and len(selected) < limit:
        # 只有更强的图谱边和正文关系都用完后，才用同册共现补齐剩余名额。
        for other_idx, edge in deferred_same_book_edges:
            other = nodes[other_idx]
            label = str(edge.get("label") or "相关人物").strip() or "相关人物"
            try:
                confidence = float(edge.get("confidence"))
            except Exception:
                confidence = None
            score = 78.0 + (confidence or 0.0) * 10.0
            try:
                score += float(edge.get("weight") or 0)
            except Exception:
                pass
            add_candidate(other, label, score, "same_book", confidence)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        fallback: List[tuple[float, str, Dict[str, Any], Optional[float]]] = []
        for node in nodes:
            name = str(node.get("person") or "").strip()
            if not name or name in seen_names:
                continue
            score = 0.0
            same_dynasty = _same_dynasty(current_dynasty, node.get("dynasty"))
            cand_tags = {
                str(x).strip()
                for x in (node.get("domain_tags") if isinstance(node.get("domain_tags"), list) else [])
                if str(x).strip()
            }
            shared_tags = current_tags & cand_tags
            cand_birth = _to_int(node.get("birth_year")) or _to_int(node.get("time_year"))
            cand_death = _to_int(node.get("death_year"))
            overlap = False
            if current_birth is not None and current_death is not None and cand_birth is not None and cand_death is not None:
                overlap = max(current_birth, cand_birth) <= min(current_death, cand_death)
            if same_dynasty:
                score += 60.0
            if overlap:
                score += 24.0
            elif current_birth is not None and cand_birth is not None:
                diff = abs(current_birth - cand_birth)
                if diff <= 30:
                    score += 18.0
                elif diff <= 80:
                    score += 10.0
                elif diff <= 160:
                    score += 4.0
            if shared_tags:
                score += 10.0 + min(12.0, 4.0 * len(shared_tags))
            if score <= 0:
                continue
            if same_dynasty and shared_tags:
                label = "同朝同领域"
            elif same_dynasty:
                label = "同时代人物"
            elif shared_tags:
                label = "同领域人物"
            elif overlap:
                label = "同时代人物"
            else:
                label = "相关人物"
            fallback.append((score, label, node, None))
        fallback.sort(key=lambda item: (item[0], str(item[2].get("person") or "")), reverse=True)
        for score, label, node, confidence in fallback:
            add_candidate(node, label, score, "fallback", confidence)
            if len(selected) >= limit:
                break

    selected = sorted(selected, key=lambda item: item.get("_score", 0), reverse=True)[:limit]
    for item in selected:
        item.pop("_score", None)

    center_file = str(current_node.get("file") or f"{display_name}.html").strip()
    center = {
        "id": display_name,
        "name": display_name,
        "file": center_file,
        "dynasty": current_dynasty,
        "aliases": [x for x in _collect_node_aliases(current_node) if str(x or "").strip() and str(x).strip() != display_name][:4],
        "birth_year": current_birth,
        "death_year": current_death,
        "quote": str(current_node.get("quote") or person.get("quote") or "").strip(),
        "review": str(current_node.get("review") or person.get("shortReview") or "").strip(),
        "foreign_name": str(current_node.get("foreign_name") or "").strip(),
        "main_role_label": str(current_node.get("main_role_label") or person.get("title") or "").strip(),
        "birthplace": str(current_node.get("birthplace") or person.get("birthplace") or "").strip(),
        "birthplace_modern": str(current_node.get("birthplace_modern") or "").strip(),
        "domain_tags": [str(x).strip() for x in (current_node.get("domain_tags") if isinstance(current_node.get("domain_tags"), list) else []) if str(x).strip()][:4],
        "has_story": bool(current_node.get("has_story", True)),
        "relationLabel": "中心人物",
        "isCenter": True,
    }
    links = [
        {
            "source": display_name,
            "target": item["name"],
            "label": item.get("relationLabel") or "相关人物",
            "confidence": item.get("confidence"),
        }
        for item in selected
    ]
    nodes_out = [center] + [{**item, "isCenter": False} for item in selected]
    return {"center": center, "nodes": nodes_out, "links": links}


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
