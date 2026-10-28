const CACHE = "fieldguard-shell-v3";
// Injected at build time (vite.config.ts): full list of hashed shell assets.
// In dev the placeholder is untouched and the fallback list below is used.
const SHELL = /*__FG_PRECACHE__*/["/", "/index.html", "/manifest.webmanifest"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api")) return;
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
