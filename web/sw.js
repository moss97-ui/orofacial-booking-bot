/* OroFacial app: works offline for the app shell; data always comes fresh from the server. */
const CACHE = "orofacial-v1";
const SHELL = ["/", "/static/styles.css", "/static/app.css", "/static/app.js", "/static/icons/icon-192.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/admin")) return;
  // Network first, so updates show at once; the cached copy is used when offline.
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && (url.pathname === "/" || url.pathname.startsWith("/static/"))) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then((m) => m || caches.match("/"))));
});
