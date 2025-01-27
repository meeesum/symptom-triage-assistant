# Phase 10a deep-dive: end-to-end test suite

First epic of the scale-up roadmap's Phase 06 (Quality at Scale) — the
final phase in the roadmap. The roadmap's own framing: "Playwright
coverage across the full patient and provider journeys, replacing the
manual browser verification this project has relied on so far." That's
a precise description of what changed: every prior epic in this project
ended with a "Live verification" section where I drove the app by hand
in a browser and wrote down what I saw. This epic turns that into
`npx playwright test`.

## Self-contained by design, not just "point it at a running app"

`frontend/playwright.config.ts` starts **both** the real FastAPI backend
and the real Next.js frontend as actual child processes via a two-entry
`webServer` array — this suite exercises the genuine HTTP/DB/job-queue
stack, not mocks or a pre-existing dev server the developer has to
remember to start first. Same "zero setup" philosophy this project
applies everywhere else (SQLite by default, fakeredis by default):
`npx playwright test` alone is enough.

A throwaway SQLite DB (`backend/.e2e-test.db`, gitignored, deleted at the
start of every run) and `REDIS_FAKE=1` keep this from touching a real
dev database or requiring a real Redis server. `ALERTING_SYNC=1`,
`RETENTION_SYNC=1`, and `REPORT_DELIVERY_SYNC=1` mirror the exact env
vars `backend/tests/conftest.py` already sets for pytest, for the
identical reason: deterministic, in-process job execution instead of
needing a real `rq worker` process running alongside the test run.
`RATE_LIMIT_ENABLED=0` avoids the exact flakiness this codebase's own
test suite already found and fixed once before (see
`docs/phase5d-api-hardening.md`) — a shared TestClient/browser IP would
otherwise trip `/auth/register`'s rate limit after five spec files worth
of test accounts.

**Port 8020, not 8000** — deliberately, so this suite never collides
with a real dev backend a developer might already have running locally
on the port every README example uses. This was found the hard way: the
first run failed with a bare "Exit code: 3" from uvicorn, which turned
out to be an *entirely unrelated* local process from a different project
already bound to port 8000 on this machine. Not a bug in this suite —
worth documenting because the failure mode (a webServer exit code, no
useful stderr surfaced by Playwright) gives no hint what actually went
wrong; the fix was choosing a port no other local project would
plausibly claim.

## Setup: API for fixtures, UI for what's actually under test

`e2e/global-setup.ts` runs once before the whole suite: deletes any
stale DB/upload dir from an interrupted previous run, runs the real
Alembic migrations directly (not relying on the backend's own startup
lifespan to have already done it — this makes the ordering between
`globalSetup` and `webServer` startup irrelevant), then bootstraps one
admin account via `scripts/create_admin.py` — the exact same
non-interactive-friendly script a real deployment operator would run,
with the password piped over stdin instead of typed (Python's
`getpass()` falls back to reading a line from stdin when there's no real
TTY attached, which is exactly this case).

`e2e/helpers.ts` draws a clear line: **API calls for setup, UI
interaction for what a spec is actually verifying.** Registering a
fixture patient, promoting a role, assigning a patient panel — all done
directly against the backend via Playwright's `request` fixture. Driving
every one of those through login/registration forms first would make
every spec slow *and* would make an unrelated login-form regression
spuriously fail specs that only needed "a logged-in provider" as a
precondition, not as the thing being tested. The one exception is
`admin-journey.spec.ts`, where the admin *promotion flow through the
`/admin` UI itself* is the actual subject.

## Specs

- **`patient-journey.spec.ts`** — registers through the real form,
  submits a self-care message and an emergency one (checking tier badge,
  emergency callout, and understood-symptom chips), the multi-turn
  follow-up-question flow (an ambiguous message → a real clarifying
  question → an answer that completes the decision), and a **real file
  upload** through the actual `<input type="file">` on a completed
  result's photo gallery.
- **`provider-journey.spec.ts`** — a provider sees a panel patient's
  emergency triage (and its attached photo, read-only — no delete
  control) on `/audit` and reflected in `/analytics`'s stats; a
  *different* provider, not on that panel, does not see it.
- **`admin-journey.spec.ts`** — promotes a patient to provider through
  the real `/admin` dropdown and confirms it survives a reload (server-
  persisted, not just local state).
- **`i18n.spec.ts`** — the language switcher actually translates visible
  UI immediately, and a Spanish emergency message gets a Spanish tier
  badge and Spanish guidance text.
- **`reports.spec.ts`** — an org_admin reaches `/analytics`, subscribes
  to scheduled reports, triggers an immediate send, and the Export
  CSV/PDF buttons trigger real browser downloads (`page.waitForEvent
  ("download")`, asserting the actual suggested filename).

## Real file uploads: closing a genuine gap in this project's own history

Every prior epic's "Live verification" used the Claude Browser MCP tool
to drive a real browser — but that tool has no file-picker/upload
capability at all. The symptom-photo-upload epic's own live verification
(`docs/phase9c-symptom-photo-upload.md`) worked around this by uploading
via `curl` directly to the API and only verifying the *read* side (the
resulting thumbnail rendering) through the browser — a real, explicitly
acknowledged gap at the time. Playwright's `setInputFiles()` closes it:
`patient-journey.spec.ts`'s photo test drives the actual `<input
type="file">` element with a real JPEG fixture
(`e2e/fixtures/test-rash.jpg`) and asserts the thumbnail appears — this
is now the first place in this project's history the *upload* side of
that flow has been verified through the browser itself, not just via
`curl`.

## Two real bugs found while writing this suite, on top of what it now guards

**A test-design lesson that surfaced real, correct app behavior**: the
first version of the self-care patient-journey test sent a bare "I have
a mild cough" and expected an immediate decision — it got a follow-up
question instead. Not a bug: the real frontend's `TriageChat.tsx` always
sets `allow_follow_up: true`, so a message missing severity/onset
correctly triggers the multi-turn confidence check
(`app/intake/conversation.py`) exactly as designed. Fixed by writing a
message with explicit severity and onset. That fix then surfaced a
*second*, subtler thing worth knowing, not a bug either: onset value
matters for which *rule* matches, not just whether a rule matches at
all — a mild cough with a **gradual** onset matches `rules.yaml`'s
`persistent_mild_symptoms` (routine tier) before it ever reaches the
`default_mild_acute` (self-care) fallback, so the test needed a
**sudden** onset specifically to exercise the self-care path it meant
to test. Both are documented inline in the spec now, not left as a
mysterious "why does this phrasing matter" for a future reader.

**A real product bug**, found incidentally while reading
`app/admin/page.tsx` to write the admin-journey spec: the role-promotion
dropdown's option list — `const ROLES: Role[] = ["patient", "provider",
"admin"]` — never included `"org_admin"` at all. This is the exact same
class of gap already found and fixed in `/audit` and `/analytics`'s
page-level role gates during the reporting-exports epic (see
`docs/phase9d-reporting-exports.md`) — a leftover from before that role
existed (`docs/phase8a-organizations.md`). The backend has accepted
`org_admin` promotions since the multi-tenancy epic; there was simply no
way to *assign* that role through this UI at all until now. Fixed
alongside writing the E2E coverage, with a dedicated regression test
(`the role dropdown offers org_admin, not just provider/admin`) asserting
the exact four-item option list.

## Verified live (by construction)

Every spec in this suite *is* the live verification — there's no
separate "then I checked it in a browser" step to write up, because
`npx playwright test` already drives a real Chromium instance against
the real running stack. Two full runs back to back (`38.0s`, `41.0s`,
both `11 passed`) confirm the suite is deterministic, not flaky —
important given it shares one backend/DB across all specs rather than
isolating each behind its own throwaway database (see "What's still
open" below for the tradeoff that implies).

## What's still open

- **Not per-spec-isolated.** All specs share one backend process and one
  SQLite DB for the whole run (`fullyParallel: false`, `workers: 1`) —
  deliberately, since spinning up a fresh backend process per spec file
  would be slow and this project's own panel-scoping/visibility rules
  are exactly the kind of thing worth testing against a shared,
  realistic-shaped dataset. The tradeoff: specs must pick distinct
  symptom text/emails to avoid colliding with each other's fixtures (see
  `provider-journey.spec.ts`'s comment on why it asserts against a
  specific record rather than a generic word that other specs' fixture
  data might also contain).
- **Chromium only.** No Firefox/WebKit projects configured — this
  project has no cross-browser compatibility requirement stated
  anywhere in its scope, and adding them would roughly triple run time
  for coverage this prototype doesn't need yet.
- **No CI wiring yet.** `.github/workflows/frontend-ci.yml` (from
  `docs/phase5c-observability-ci.md`) still only runs `tsc`/`next
  build`, not this suite — running Playwright in CI needs the backend's
  Python venv set up in that job too, which the roadmap's own **Cross-
  phase contract tests** epic (the third epic of this same phase) is a
  more natural place to wire up correctly, at the same time integration-
  level CI gets built out generally, rather than bolting it onto the
  existing frontend-only job piecemeal.
- **No accessibility (a11y) assertions.** Coverage here is functional
  (does the right thing render, does the right data appear), not an
  automated a11y audit (e.g. `axe-core`) — a real gap for a healthcare
  product, tracked but not addressed by this epic.
- **The photo-upload spec's fixture image** (`e2e/fixtures/test-rash.jpg`)
  is a flat 60×60 solid-color JPEG generated for this suite — a real
  photo would obviously look nothing like it; it exists only to be a
  valid, small, real JPEG the upload pipeline's actual validation
  (`Pillow` decode + format check) has to genuinely accept, not a
  hand-crafted or corrupted test double.
