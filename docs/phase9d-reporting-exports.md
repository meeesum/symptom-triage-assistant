# Phase 9d deep-dive: reporting exports

Fourth and final epic of the scale-up roadmap's Phase 05 (Reach &
Polish) — **Phase 05 is now complete.** The roadmap's scope: "CSV and
PDF exports off the provider analytics dashboard, plus scheduled report
delivery for org admins," depending on the Provider analytics dashboard
(Phase 03, `docs/phase7d-provider-analytics.md`).

## Two exports, deliberately different data, not the same shape twice

`app/services/reporting.py` builds two distinct artifacts, not one
dataset reshaped:

- **CSV** (`build_audit_csv`) — the underlying raw audit records, one
  row per triage decision. What someone would actually pull into a
  spreadsheet for their own analysis.
- **PDF** (`build_analytics_pdf`) — a formatted, shareable summary
  document (tier distribution, daily volume, follow-up stats), built
  with `reportlab` (pure Python, no system dependencies like Cairo/Pango
  that `weasyprint`-style HTML-to-PDF tools need — a real portability
  concern for a project that otherwise runs with zero native
  dependencies beyond what pip installs). The PDF reuses
  `app/services/analytics.py`'s aggregation functions directly rather
  than re-deriving the numbers, so it can never drift from what
  `/analytics` itself shows for the same window.

Both take `(role, user_id, org_id, days)` and apply the exact same
`audit_visibility_clause()` panel/org scoping as `GET /audit/recent` and
`GET /audit/analytics` — an export is not a way around visibility
scoping, it's the same scoped data in a different shape. Verified with a
dedicated test that creates an in-panel and an out-of-panel record and
confirms the CSV contains one and not the other.

## Scheduled delivery: same two-phase job-queue pattern as every prior job feature

`app/services/report_delivery.py` mirrors `app/services/alerting.py` and
`app/services/retention.py` exactly: an API-triggered send (`POST
/reports/subscription/send-now`) enqueues via RQ so the request returns
immediately instead of blocking on PDF generation + an SMTP round trip;
the actual cron entry point (`scripts/run_scheduled_reports.py`) calls
`run_due_reports()` directly and synchronously, since the script itself
*is* the explicit, out-of-band trigger — the same split
`scripts/run_retention_purge.py` already established, for the identical
reason.

`ReportSubscription` (one row per user, same lazy-row pattern as
`NotificationPreference`) stores `frequency` (daily/weekly/monthly),
`report_format` (csv/pdf/both), and `last_sent_at`. `is_due()` is
deliberately simple — "has enough calendar time passed since
`last_sent_at`" — not a cron-expression scheduler; good enough for what
the roadmap actually asks for.

Self-service subscription management (`GET`/`PUT`/`DELETE
/reports/subscription`) is gated to **`org_admin` specifically**, not
`provider`/`admin` — a recurring digest is only meaningful for an
org-wide view (`org_admin`'s scope), where a `provider`'s narrower
panel-scoped view is already visible live on `/analytics` any time they
want it without needing a digest at all.

## A real SQLite timezone bug, caught by the test before it ever ran live

`is_due()`'s first implementation did `now - subscription.last_sent_at`
directly on a value read back from the DB. This worked in a quick manual
check but failed the moment a real test asserted on it:
`TypeError: can't subtract offset-naive and offset-aware datetimes`.
SQLite's `DateTime(timezone=True)` column type doesn't actually preserve
timezone info the way Postgres does — every write in this codebase uses
`datetime.now(UTC)`, but reading it back from SQLite gives a *naive*
datetime. Every prior epic's datetime handling sidestepped this by doing
comparisons at the SQL level (`WHERE created_at >= :since`, which
SQLAlchemy translates correctly regardless of storage timezone
awareness) — this was the first feature in the codebase to do a
**Python-level** arithmetic comparison on a DB-loaded timestamp, which is
exactly what exposed the gap. Fixed by normalizing a naive
`last_sent_at` to UTC-aware before comparing (safe, since every write
path uses UTC); covered by three tests exercising the not-yet-sent,
recently-sent, and due-again cases directly.

## A second real bug, found by trying to actually verify the feature

Live-verifying the "send now" flow initially showed `last_sent_at` never
advancing. The cause: the app's real (non-test) default runs the job
queue **async** — a genuine, correct operational requirement, same as
every other job-queue feature here — meaning the job sits on real Redis
until an actual `rq worker scheduled_reports` process picks it up.
Confirmed the job genuinely queued (`redis-cli LLEN
rq:queue:scheduled_reports` → 1) before concluding anything was wrong,
then started a real worker and watched it complete the job and advance
`last_sent_at` — the same verification discipline
`docs/phase7e-high-risk-alerting.md` established for alerts.

That investigation surfaced a real **design** question worth fixing, not
just an environment quirk: should `last_sent_at` advance even when
delivery genuinely fails (e.g. SMTP down)? The first version, mirroring
`alerting.py`'s `Alert.status` (which stays `"sent"` even on a failed
notification, because the durable `Alert` *row* is the artifact that
matters), unconditionally bumped `last_sent_at` regardless of send
success. But a report has no separate durable record the way an alert
does — unconditionally advancing the timestamp on a failed send would
make a persistent SMTP outage **invisible**: the next scheduled run
would see a "recently sent" timestamp and skip, even though the
org_admin never received anything. Fixed so `last_sent_at` only advances
on at least partial delivery success, letting `run_due_reports()`
naturally retry a failed subscription on its next cron run instead of
silently going quiet forever. Covered by a dedicated test using a fake
always-fails email client.

## A third, unrelated bug found along the way: org_admin was locked out of its own dashboard

Building the subscription UI meant putting it on `/analytics` — but the
frontend's client-side role gate on both `/audit/page.tsx` and
`/analytics/page.tsx` only ever checked for `"provider"` and `"admin"`,
never `"org_admin"` — a leftover from before that role existed
(`docs/phase8a-organizations.md`), even though the **backend** endpoints
have accepted `org_admin` since the org_admin access-gap fix in
`docs/phase8c-admin-action-audit-log.md`. An org_admin hitting either
page got a client-side "forbidden" message despite the API underneath
being fully willing to serve them. This surfaced immediately once
org_admin-only UI needed to render on that page — it was completely
unreachable otherwise. Digging one level further: `lib/api.ts`'s `Role`
TypeScript type itself never included `"org_admin"` at all, which is
*why* the page-level checks were wrong in the first place — TypeScript
caught this the moment the gate checks were fixed to compare against
`"org_admin"`, since the type had no idea the value could exist
(`This comparison appears to be unintentional because the types ...
have no overlap`). Fixed all three: the `Role` type, and both pages'
gates. Verified live: logged in as a real org_admin account and loaded
both `/audit` and `/analytics` successfully for the first time.

## Live verification

1. `curl`-verified CSV export: real header row, real audit records
   (from this session's own accumulated history across every prior
   epic's live verification), correctly scoped.
2. `curl`-verified PDF export: downloaded, confirmed `file` reports "PDF
   document, version 1.4, 2 pages," then actually read the rendered
   content — correct title, real tier counts (emergency: 3, routine: 7,
   self_care: 1 — matching the live data), correct daily volume table,
   properly styled header rows.
3. Registered a real account, promoted it to `org_admin` directly in the
   DB (mirroring `scripts/create_admin.py`'s own bootstrap pattern),
   subscribed via the real API, called `send-now`, confirmed the job
   landed in real Redis (not just a mock), started a real `rq worker
   scheduled_reports --burst` process, watched it complete the job, and
   confirmed `last_sent_at` advanced.
4. In the actual browser: logged in as that org_admin, loaded
   `/analytics` (previously would have shown "forbidden" — now works),
   saw the real Export CSV / Export PDF report buttons and a Scheduled
   Reports panel pre-populated with the real subscription state set up
   via curl. Clicked "Send now" from the UI itself, confirmed a new job
   landed in Redis, processed it with a real worker, reloaded the page,
   and confirmed the UI's displayed `last_sent_at` advanced to the
   worker's actual processing time. Clicked both export buttons and
   confirmed real `200` network responses for `/audit/export.csv` and
   `/audit/analytics/export.pdf`. Also loaded `/audit` as the same
   org_admin to confirm that gate's fix independently.
5. Proactively cleared the PWA service worker's cache before testing
   this time (a real, reproducible gotcha this project's own
   `docs/phase9c-symptom-photo-upload.md` already documented) — avoided
   repeating that debugging detour.

## What's still open

- **No timezone-of-recipient awareness.** `is_due()` operates purely in
  UTC calendar days — a "daily" report always fires roughly 24 hours
  after the last send in UTC, not at a fixed local time for the
  recipient. Fine for this epic's actual requirement; a real product
  would likely want "send at 8am recipient-local-time."
- **`report_format: "both"` sends two separate attachments in one
  email**, not a combined document — simplest correct behavior, but
  worth knowing if a recipient expects one file.
- **No UI for the CSV/PDF `days` window** — both export buttons always
  request the same 30-day default the dashboard itself uses; there's no
  control to export a different window than what's currently displayed.
- **No retry backoff or max-attempt cap** on a persistently-failing
  subscription — `run_due_reports()` will keep retrying a subscription
  whose email keeps failing on every cron run indefinitely, forever,
  with no escalation or auto-unsubscribe. Acceptable for a prototype;
  a real deployment would want at least a logged/alerted threshold.
- **Real SMTP delivery is unverified in this sandbox** — same caveat as
  every other real-network-credential path in this codebase (no real
  `SMTP_HOST`/`ANTHROPIC_API_KEY`/`TWILIO_ACCOUNT_SID` configured here).
  The `ConsoleNotificationClient` fallback logs structurally instead,
  and the attachment-carrying code path (`send_with_attachment`) was
  exercised in tests via a fake email client, not a real SMTP server —
  unlike `docs/phase7f-notifications.md`'s STARTTLS fix, which *was*
  verified against a real local debug SMTP server.

## Test coverage added

- `tests/test_reporting_service.py` (5 tests) — CSV header/content
  correctness, panel-scoping enforcement, real PDF byte generation,
  zero-record edge case.
- `tests/test_report_delivery_service.py` (12 tests) — subscription
  CRUD, `is_due()` across never-sent/recently-sent/due-again cases (the
  SQLite timezone bug lives here), send job success/failure paths
  (including the failure-doesn't-advance-timestamp regression test),
  `run_due_reports()` filtering.
- `tests/test_reports_api.py` (14 tests) — export endpoint role gating
  (patient/provider/admin), subscription endpoint role gating
  (org_admin-only), validation (invalid frequency/format), the full
  subscribe → send-now → cancel lifecycle.

All 457 backend tests pass (426 pre-existing + 31 new across this
epic), zero regressions; `ruff check` clean; frontend `tsc --noEmit` and
`next build` both clean.

**This completes Phase 05 (Reach & Polish) of the scale-up plan** — all
four epics (responsive redesign + PWA, internationalization, symptom
photo upload, reporting exports) are done, tested, and documented.
