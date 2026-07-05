/* StoryMap Service Worker — 缓存静态资源，二次访问几乎零网络请求 */
const CACHE_NAME = 'storymap-v1';

const STATIC_ASSETS = [
  '/',           // 首页
  './vendor/preact-compat.production.min.js',
  './vendor/babel.min.js',
  './static/profile-app.js',
  './static/design-tokens.css',
  './static/tailwind.css',
  './orange.png',
];

const PORTRAIT_PATTERN = /\.\/portraits\/.*\.(jpg|jpeg|png|webp|svg)$/;
const STATIC_DIR_PATTERN = /\.\/static\/.*\.(js|css)$/;
const VENDOR_PATTERN = /\.\/vendor\/.*\.(js|css)$/;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // HTML pages: network-first, fallback to cache
  if (event.request.destination === 'document' || url.pathname.endsWith('.html')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Vendor & static assets: cache-first
  if (VENDOR_PATTERN.test(url.pathname) || STATIC_DIR_PATTERN.test(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
    return;
  }

  // Portrait images: cache-first
  if (PORTRAIT_PATTERN.test(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }
});
