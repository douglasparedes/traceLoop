// FieldGuard service worker v4.
// Shell: precached at build time (hashed list injected into SHELL), network-first
// at runtime with navigation fallback so the app opens offline.
// Media: runtime cache-first for evidence/reference images and tutorial/live
// videos. App JSON (/api/*) is NEVER cached here — procedure/job state syncs
// through IndexedDB + explicit sync events, and a stale cached response would
// corrupt that flow. Media URLs carry per-session ?token= params, so cache keys
// are normalized to the bare pathname.
const CACHE = "fieldguard-shell-v4";
const MEDIA_CACHE = "fieldguard-media-v1";
const MEDIA_MAX_ENTRIES = 120;

// Injected at build time (vite.config.ts): full list of hashed shell assets.
// In dev the placeholder is untouched and the fallback list below is used.
const SHELL = /*__FG_PRECACHE__*/["/", "/index.html", "/manifest.webmanifest"];

const MEDIA_RE = /^\/api\/(evidence\/[^/]+\/image|tutorial\/[^/]+\/video|live-recordings\/[^/]+\/chunks\/\d+\/video)$/;

function mediaKey(url) {
  return url.origin + url.pathname;
}

async function trimMedia() {
  try {
    const c = await caches.open(MEDIA_CACHE);
    const keys = await c.keys();
    if (keys.length > MEDIA_MAX_ENTRIES) {
      await Promise.all(keys.slice(0, keys.length - MEDIA_MAX_ENTRIES).map((k) => c.delete(k)));
    }
  } catch { /* quota/privacy mode: media just stays network-only */ }
}

async function mediaFirst(request, key) {
  const c = await caches.open(MEDIA_CACHE);
  const hit = await c.match(key);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && res.ok) {
    try {
      await c.put(key, res.clone());
      void trimMedia();
    } catch { /* quota exceeded: serve the network copy, skip caching */ }
  }
  return res;
}

self.addEventListener("install", (e) => {
  // No skipWaiting: a waiting worker only activates on user-approved reload,
  // so an in-progress guided job is never yanked out from under the tech.
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE && k !== MEDIA_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // Runtime media cache (offline reference photos + tutorial/live videos).
  if (url.origin === self.location.origin && MEDIA_RE.test(url.pathname)) {
    const key = mediaKey(url);
    e.respondWith(
      mediaFirst(e.request, key).catch(() => caches.open(MEDIA_CACHE).then((c) => c.match(key)))
    );
    return;
  }
  if (url.pathname.startsWith("/api")) return;
  const isNavigation = e.request.mode === "navigate";
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok) {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return r;
    }).catch(async () => {
      const cached = await caches.match(e.request);
      if (cached) return cached;
      if (isNavigation) return (await caches.match("/index.html")) || Response.error();
      return Response.error();
    })
  );
});
