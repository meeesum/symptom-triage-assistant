// Service worker for the "installable PWA" half of Phase 05's
// responsive-redesign-+-PWA epic. Deliberately narrow in what it caches —
// this is a health-triage app, and offline-serving a STALE triage
// response would mean showing a patient guidance that might no longer be
// correct with no way for them to tell. See docs/phase9a-responsive-and-pwa.md.
//
// What's cached: the app shell (the pages/scripts/styles Next.js needs
// to render the UI at all) and static assets, so the app opens instantly
// and shows *something* even with no connectivity, instead of a blank
// browser error page.
// What's NEVER cached: any request to the backend API — /triage/*,
// /audit/*, /auth/*, etc. Those always go to the network, and a failed
// one fails visibly (the existing "Couldn't reach the triage service"
// error path in lib/api.ts), never silently serving old data for
// anything safety-relevant.

const CACHE_NAME = "triage-shell-v1";
const SHELL_ASSETS = ["/", "/manifest.json", "/offline.html"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

function isApiRequest(url) {
  // Same-origin API base isn't used here — the backend runs on its own
  // origin (see NEXT_PUBLIC_API_BASE_URL) — but this also guards any
  // same-origin /api/* route this app might add later.
  return url.pathname.startsWith("/api/");
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Cross-origin (the backend API) or same-origin /api/* — network only,
  // never cached, never served stale. Let it fail naturally if offline;
  // lib/api.ts already has a real error message for that case.
  if (url.origin !== self.location.origin || isApiRequest(url)) {
    return;
  }

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/offline.html"))
    );
    return;
  }

  // Static assets (Next's _next/static/*, icons, etc.) — cache-first for
  // speed, falling back to network and populating the cache for next time.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
