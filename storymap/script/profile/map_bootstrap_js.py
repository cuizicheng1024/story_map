"""地图运行时引导 JS。

参照 tooltip_js.py 的模式，将 ~400 行内联 JS 从 renderer.py 提取为独立模块，
便于用 JS 工具链进行语法检查与格式化。
"""

from __future__ import annotations


def amap_bootstrap_js() -> str:
    """返回高德地图 AMap 运行时脚本加载器（纯 JS，不含 <script> 标签）。"""
    return r"""
window.__MAP_STORY_RUNTIME_SCRIPT_PROMISES__ = window.__MAP_STORY_RUNTIME_SCRIPT_PROMISES__ || {};
window.__MAP_STORY_RUNTIME_CONFIG_PROMISES__ = window.__MAP_STORY_RUNTIME_CONFIG_PROMISES__ || {};
window.__MAP_STORY_RUNTIME_CONFIG_CANDIDATES__ = window.__MAP_STORY_RUNTIME_CONFIG_CANDIDATES__ || function(filename) {
  const out = [];
  const seen = new Set();
  const push = (url) => {
    const normalized = String(url || '').trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    out.push(normalized);
  };
  try {
    // Resolve the runtime config URL.
    //
    // Order of candidates:
    //   1. Same-origin relative URL (always, unless served from file://).
    //      Most production deployments — both OpenDeploy and the Volcano
    //      Engine ECS — proxy /amap-config.js and /geovis-config.js on
    //      the same origin as the HTML, so the relative URL is the
    //      cleanest path. Skipping file:// preserves the static-build
    //      behaviour.
    //   2. MAP_STORY_API_BASE + filename (explicit override, used when
    //      the API runs on a different origin than the page).
    if (window.location && window.location.protocol !== 'file:') {
      push(new URL(`./${String(filename || '').replace(/^\/+/, '')}`, window.location.href).toString());
    }
  } catch (_) {}
  try {
    const apiBase = String(window.MAP_STORY_API_BASE || '').trim();
    if (apiBase) {
      push(apiBase.replace(/\/+$/, '') + '/' + String(filename || '').replace(/^\/+/, ''));
    }
  } catch (_) {}
  return out;
};
window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__ = window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__ || function(options) {
  const opts = options && typeof options === 'object' ? options : {};
  const cacheKey = String(opts.cacheKey || '').trim();
  const src = String(opts.src || '').trim();
  const checkReady = typeof opts.checkReady === 'function' ? opts.checkReady : null;
  const timeoutMs = Math.max(1000, Number(opts.timeoutMs || 12000));
  const loadError = String(opts.loadError || 'SCRIPT_LOAD_FAILED');
  const timeoutError = String(opts.timeoutError || 'SCRIPT_LOAD_TIMEOUT');
  if (checkReady && checkReady()) return Promise.resolve(true);
  if (!cacheKey || !src) return Promise.reject(new Error('SCRIPT_SRC_REQUIRED'));
  const registry = window.__MAP_STORY_RUNTIME_SCRIPT_PROMISES__ || (window.__MAP_STORY_RUNTIME_SCRIPT_PROMISES__ = {});
  if (registry[cacheKey]) return registry[cacheKey];
  const promise = new Promise((resolve, reject) => {
    let settled = false;
    let timer = 0;
    let script = document.querySelector(`script[data-runtime-key="${cacheKey}"]`);
    if (script && script.getAttribute('data-runtime-state') === 'error') {
      try { script.remove(); } catch (_) {}
      script = null;
    }
    const cleanup = () => {
      if (timer) {
        try { window.clearTimeout(timer); } catch (_) {}
        timer = 0;
      }
      if (!script) return;
      try { script.removeEventListener('load', onLoad); } catch (_) {}
      try { script.removeEventListener('error', onError); } catch (_) {}
    };
    const succeed = () => {
      if (settled) return;
      settled = true;
      if (script) script.setAttribute('data-runtime-state', 'loaded');
      cleanup();
      registry[cacheKey] = Promise.resolve(true);
      resolve(true);
    };
    const fail = (err) => {
      if (settled) return;
      settled = true;
      if (script) script.setAttribute('data-runtime-state', 'error');
      cleanup();
      delete registry[cacheKey];
      reject(err);
    };
    const onLoad = () => {
      if (checkReady && !checkReady()) {
        fail(new Error(loadError));
        return;
      }
      succeed();
    };
    const onError = () => fail(new Error(loadError));
    if (!script) {
      script = document.createElement('script');
      script.async = true;
      script.src = src;
      script.setAttribute('data-runtime-key', cacheKey);
      script.setAttribute('data-runtime-state', 'loading');
      document.head.appendChild(script);
    } else if (script.getAttribute('data-runtime-state') === 'loaded' && (!checkReady || checkReady())) {
      succeed();
      return;
    }
    try { script.addEventListener('load', onLoad, { once: true }); } catch (_) {}
    try { script.addEventListener('error', onError, { once: true }); } catch (_) {}
    timer = window.setTimeout(() => {
      if (checkReady && checkReady()) {
        succeed();
        return;
      }
      fail(new Error(timeoutError));
    }, timeoutMs);
  });
  registry[cacheKey] = promise;
  return promise;
};
window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__ = window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__ || function(kind, filename, isReady) {
  if (typeof isReady === 'function' && isReady()) return Promise.resolve(true);
  const registry = window.__MAP_STORY_RUNTIME_CONFIG_PROMISES__ || (window.__MAP_STORY_RUNTIME_CONFIG_PROMISES__ = {});
  const cacheKey = `config:${String(kind || filename || 'runtime')}`;
  if (registry[cacheKey]) return registry[cacheKey];
  const promise = (async () => {
    const urls = window.__MAP_STORY_RUNTIME_CONFIG_CANDIDATES__(filename);
    for (let idx = 0; idx < urls.length; idx += 1) {
      const url = urls[idx];
      try {
        await window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__({
          cacheKey: `${cacheKey}:${idx}:${url}`,
          src: url,
          checkReady: isReady,
          timeoutMs: 4000,
          loadError: `${String(kind || 'config').toUpperCase()}_CONFIG_LOAD_FAILED`,
          timeoutError: `${String(kind || 'config').toUpperCase()}_CONFIG_LOAD_TIMEOUT`,
        });
      } catch (_) {}
      if (typeof isReady === 'function' && isReady()) return true;
    }
    return typeof isReady === 'function' ? isReady() : false;
  })();
  registry[cacheKey] = promise.finally(() => {
    if (typeof isReady === 'function' && isReady()) {
      registry[cacheKey] = Promise.resolve(true);
    } else {
      delete registry[cacheKey];
    }
  });
  return registry[cacheKey];
};
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
  const finish = async () => {
    try {
      await window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__('amap', 'amap-config.js', () => Boolean(_getAmapKey()));
    } catch (_) {}
    const key = _getAmapKey();
    if (!key) throw new Error('AMAP_KEY_REQUIRED');
    const sec = _getAmapSecurity();
    if (sec) {
      window._AMapSecurityConfig = { securityJsCode: sec };
    }
    await window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__({
      cacheKey: 'amap-sdk',
      src: `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&plugin=AMap.TileLayer.Satellite,AMap.TerrainLayer`,
      checkReady: () => Boolean(window.AMap && typeof window.AMap.Map === 'function'),
      timeoutMs: 12000,
      loadError: 'AMAP_LOAD_FAILED',
      timeoutError: 'AMAP_LOAD_TIMEOUT',
    });
    return true;
  };
  finish().then(resolve).catch(reject);
});
""".strip()


def map_bootstrap_js() -> str:
    """返回 MapLibre / Cesium / GeoVis 运行时引导 JS（纯 JS，不含 <script> 标签）。"""
    return r"""
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
  if (typeof window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__ !== 'function') {
    return reject(new Error('MAPLIBRE_LOADER_UNAVAILABLE'));
  }
  window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__({
    cacheKey: 'maplibre-sdk',
    src: jsSrc,
    checkReady: () => Boolean(window.maplibregl && typeof window.maplibregl.Map === 'function'),
    timeoutMs: 12000,
    loadError: 'MAPLIBRE_LOAD_FAILED',
    timeoutError: 'MAPLIBRE_LOAD_TIMEOUT',
  }).then(resolve).catch(reject);
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
  if (typeof window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__ !== 'function') {
    return reject(new Error('CESIUM_LOADER_UNAVAILABLE'));
  }
  window.__MAP_STORY_ENSURE_RUNTIME_SCRIPT__({
    cacheKey: 'cesium-sdk',
    src: jsSrc,
    checkReady: () => Boolean(window.Cesium && typeof window.Cesium.Viewer === 'function'),
    timeoutMs: 16000,
    loadError: 'CESIUM_LOAD_FAILED',
    timeoutError: 'CESIUM_LOAD_TIMEOUT',
  }).then(resolve).catch(reject);
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
  ensureConfig: () => (
    typeof window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__ === 'function'
      ? window.__MAP_STORY_ENSURE_RUNTIME_CONFIG__('geovis', 'geovis-config.js', () => Boolean(_getGeoVisToken()))
      : Promise.resolve(Boolean(_getGeoVisToken()))
  ),
  tileUrl: _geoVisTileUrl,
  terrainServiceUrl: _geoVisTerrainServiceUrl,
  terrainRootUrl: _geoVisTerrainRootUrl,
  probeTile: _probeGeoVisTile,
  ensureMapLibre: _ensureMapLibre,
  ensureCesium: _ensureCesium,
  buildMapLibreStyle: _buildGeoVisMapLibreStyle,
  applyMapLibreMode: _applyGeoVisMapLibreMode
};
""".strip()
