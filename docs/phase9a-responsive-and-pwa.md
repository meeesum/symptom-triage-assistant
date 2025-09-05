# Phase 9a deep-dive: responsive redesign + PWA

First epic of the scale-up roadmap's Phase 05 (Reach & Polish) — "what
makes everything above usable by more people, on more devices." This is
the first Phase 05 epic, and the first genuinely frontend-heavy epic
since Phase 03's analytics dashboard.

## A real mobile bug found by actually resizing the browser, not guessing

Before changing anything, the existing pages were checked at a real
375×812 mobile viewport. Most of them — the triage chat, the audit
table (already had `overflow-x: auto`), the analytics stat-tile grid
(already `repeat(auto-fit, minmax(...))`) — turned out to already be
responsive, built that way from the start rather than needing rework.

**The navbar was genuinely broken.** Logged in as admin (4 nav links +
"signed in as admin" + a Log out button), the flexbox row had no wrap
behavior at all. At mobile width, `read_page` showed a real `button "Log
out"` in the DOM, but the screenshot showed it visually cut off outside
the navbar's bounds — a real, reachable-in-code but practically
unusable Log out button on any phone. Fixed with `flex-wrap` on both the
navbar and its links row, plus a `max-width: 480px` breakpoint that
stacks the nav-links group above the auth group entirely rather than
letting them fight for one wrapped line. Verified by reloading the same
page at the same viewport: links wrap cleanly onto two lines, "signed in
as admin" and "Log out" render fully visible and clickable.

## What's built for the PWA half

- `frontend/public/manifest.json` — name, icons, `display: "standalone"`,
  theme color matching the app's own `--accent`.
- **Real PNG icons**, not placeholders — generated with Pillow (192×192,
  512×512, and a 180×180 Apple touch icon), a simple rounded-square
  accent-blue background with a white medical-cross glyph. Verified live:
  fetched `/icons/icon-192.png` and `/icons/icon-512.png` from the
  running dev server, both returned real `200`s with actual image bytes,
  not 404s.
- `frontend/public/sw.js` — a service worker, registered via a small
  client component (`ServiceWorkerRegister.tsx`) in the root layout.
- `frontend/public/offline.html` — a static fallback page shown when a
  navigation fails with no network.
- `app/layout.tsx` gained a `manifest`/`icons` metadata block and a
  `Viewport` export (width, initial scale, theme color) — the standard
  Next.js App Router way to emit the manifest link and viewport meta tag.

## The service worker's scope is deliberately narrow — and why

This is a health-triage app; the risk with a naive "cache everything for
offline" service worker isn't inconvenience, it's showing a patient a
**stale triage response** with no way for them to tell it's stale. So:

- **Cached**: the app shell (`/`, `/manifest.json`, `/offline.html`) at
  install time, plus static JS/CSS/icon assets opportunistically
  (cache-first) as they're requested during normal use — this is what
  makes the app open instantly and show *something* offline instead of a
  blank browser error.
- **NEVER cached**: any cross-origin request (the backend API lives on
  its own origin) or any same-origin `/api/*` path. Those always hit the
  network and fail visibly through the existing error handling in
  `lib/api.ts` ("Couldn't reach the triage service...") rather than
  silently serving an old response for anything safety-relevant.

Verified live, not just read from the code: after loading the app with
the service worker registered, inspected the actual `CacheStorage`
contents directly — the cache held exactly the app shell (HTML, JS/CSS
chunks, manifest, icons, offline page) and nothing else; no API response
of any kind was present.

## A false alarm caught and correctly diagnosed, not chased

After restarting the dev server, the browser console showed a
`ReactDevOverlay`/`scheduler.development.js` "Cannot read properties of
undefined" error. Rather than assuming it was a bug in this epic's
changes, it was checked concretely: unregistered the service worker,
cleared all caches, reloaded — the console error persisted unchanged, but
a screenshot of the actual page showed it rendering perfectly, and a full
multi-turn triage conversation ("I have a mild cough" → the real
severity/onset follow-up questions → a real routine-tier decision)
completed correctly end to end. This confirmed the console noise was a
benign Next.js dev-mode error-overlay artifact from the server restart
itself (a well-known class of dev-only React Fast Refresh glitch), not a
regression from this epic's changes — worth stating explicitly rather
than either ignoring a real error or wrongly attributing a cosmetic one
to real code.

## What's still open

- **No provider-dashboard-specific mobile layout beyond the fixes
  above** — the existing pages (audit, analytics, admin) work on mobile
  now, but nothing was purpose-built as a distinct "mobile provider
  view" (e.g. a condensed audit list instead of a scrolling table). The
  roadmap's own framing ("a real mobile layout for the triage chat and
  provider dashboard") is satisfied by making the existing responsive
  patterns actually work everywhere, not by a from-scratch mobile-first
  redesign.
- **No "Add to Home Screen" install prompt UI** — the manifest makes the
  app installable via the browser's own native install affordance
  (address-bar icon on desktop Chrome, share-sheet "Add to Home Screen"
  on mobile Safari/Chrome), but there's no custom in-app prompt
  encouraging it.
- **The service worker has no update-notification UX** — a new
  deployment updates the cache (`CACHE_NAME` version bump invalidates the
  old one on activate) but doesn't tell an already-open tab "a new
  version is available, reload to update."
- **No Lighthouse/PWA-audit run in this sandbox** — verified the
  concrete, checkable claims (manifest loads, icons are real images, SW
  registers and activates, cache contents are correct, offline fallback
  exists) directly; a full Lighthouse PWA score wasn't run here.
