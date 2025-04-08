# Phase 5d deep-dive: API hardening

Fourth and final epic of the scale-up roadmap's Phase 01 (Production
Foundations) — with this, Phase 01 is complete.

## What's built

- `app/core/rate_limit.py` — a `slowapi` `Limiter`, backed by the same
  Redis instance as token tracking when one's configured (counters
  survive an app restart and are shared correctly across replicas — an
  in-process counter would reset on redeploy and be wrong behind more
  than one instance). Falls back to `slowapi`'s `memory://` store under
  `REDIS_FAKE=1`, same zero-setup guarantee as everything else.
- Applied narrowly, not globally: `POST /auth/register` (5/min),
  `POST /auth/login` (10/min), `POST /auth/refresh` (30/min) — the
  endpoints where abuse has an obvious concrete cost (credential
  stuffing, mass account creation, token-rotation hammering). The triage
  endpoints stay unlimited — they're the product's core anonymous-use
  path, and a blanket limit there needs product input on what legitimate
  usage looks like, not an engineering default guessed at here.
- `app/core/request_limits.py` — a 1 MiB request body cap, checked via
  `Content-Length` before the body is even read. Explicitly framed as
  defense in depth: a real deployment's reverse proxy (nginx
  `client_max_body_size` or equivalent) is a better place for this
  (rejects oversized requests before they cost an app worker anything),
  but this middleware keeps the limit enforced when running the app
  directly, without a proxy in front yet.
- OpenAPI enrichment: `openapi_tags` on the FastAPI app (descriptions per
  router group, not just names) and `Field(examples=[...])` on the
  request bodies most worth seeing a real example for (register, login,
  triage intake) — makes `/docs` actually useful instead of empty
  placeholder forms.

## A real test-isolation bug the rate limiter caused, caught immediately

Wiring `@limiter.limit(...)` onto `/auth/register` and running the test
suite immediately broke 30 unrelated tests — `starlette.testclient
.TestClient` always presents the same synthetic remote address, so every
test in the suite appeared to come from one "IP" and blew through the
5/minute limit within the first handful of registrations. Fixed the same
way the SQLite/fakeredis defaults are handled: `RATE_LIMIT_ENABLED=0` by
default in `tests/conftest.py`, with `tests/test_rate_limiting.py`
explicitly flipping `limiter.enabled = True` (and calling `.reset()` to
clear any prior counts) for its own scope, restoring it afterward via a
fixture. This is NOT the same category of thing as the SQLite/Postgres or
fakeredis/Redis defaults — those are "skip a real backing service you
don't need for tests." This is "a real behavior would otherwise throttle
the test suite itself," a genuine necessity, documented as such rather
than silently glossed over.

Verified live against a real running server (not just pytest): hammered
`/auth/register` 6 times with curl — the first 5 succeeded (`201`), the
6th got `429`. Also verified the readiness endpoint (`docs/phase5c-observability-ci.md`)
correctly returns `503` when Redis is killed mid-run, `database: true` /
`redis: false` in the response body — the two checks are genuinely
independent, not just decorative.

## API versioning: a decision, not an oversight

The roadmap listed "a versioning strategy for the API surface" as part of
this epic. The decision made here is explicit: **no `/v1/...` URL prefix
yet.** Reasoning:

- There is exactly one consumer of this API right now — this repo's own
  Next.js frontend, deployed and versioned in lockstep with the backend.
  A version prefix exists to let old and new API shapes coexist for
  clients that can't update in lockstep with the server; with a single,
  co-deployed consumer, that problem doesn't exist yet.
- Adding `/v1/` now would touch every route, every frontend fetch call,
  and every test's URL string — real churn — to guard against a
  compatibility problem that isn't real yet. That's the same "don't add
  complexity before it's needed" judgment this project has applied
  elsewhere (e.g. not building multi-tenancy before there's a second
  tenant).

**Trigger conditions for when to actually add it** (so this isn't just
deferred forever without a plan):
1. A second consumer of the API shows up that can't be redeployed in
   lockstep with the backend (a mobile app, a third-party integration,
   Phase 03's provider analytics dashboard if it ends up as a separately
   deployed service).
2. A breaking change is needed to an endpoint a consumer depends on and
   there's no way to make it additive.

When either happens, the plan is path-based versioning (`/v1/triage/...`)
rather than header-based (`Accept: application/vnd.triage.v1+json`) —
simpler to route, cache, and debug, at the cost of being slightly less
RESTful-purist; a reasonable tradeoff for this product's shape.

## What's still open

- No API key / client-credential system for non-browser consumers — not
  needed while the only consumer is the first-party frontend.
- Rate limits are a first guess (5/10/30 per minute), not tuned against
  real traffic patterns — revisit once there's real usage data from a
  pilot (see the original 12-month roadmap's Phase 5).
- The 1 MiB request-body cap doesn't protect against a request that lies
  about its `Content-Length` or omits it — bounded only by
  Starlette/uvicorn's own defaults in that case, not by this middleware
  specifically. A real deployment's reverse proxy should be the primary
  defense here, not this middleware alone.
