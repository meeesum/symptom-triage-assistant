# Phase 7e deep-dive: high-risk alerting + job queue

Fifth epic of the scale-up roadmap's Phase 03 (Provider & Care-Team
Platform) — the first epic in this project to introduce a real
asynchronous job queue, decoupling work from the request/response cycle
instead of everything happening inline.

## What's built

- **RQ chosen over Celery.** The roadmap named either as acceptable. RQ
  reuses this project's existing Redis infrastructure directly (same
  `REDIS_URL`/`REDIS_FAKE` duality already established for token
  tracking and rate limiting — see `docs/phase5b-redis-token-tracking.md`)
  with no separate broker service to stand up; Celery would need one
  (typically Redis or RabbitMQ configured as a distinct broker role, plus
  its own worker bootstrapping). Given this codebase's Redis is already
  first-class infrastructure, RQ was the lighter-weight fit.
- `app/core/queue_client.py` — a SEPARATE Redis connection from
  `app/core/redis_client.py`'s singleton, not a reuse of it. RQ needs raw
  bytes back from Redis (it pickles job payloads); the existing client is
  constructed with `decode_responses=True`, correct for the plain-string
  token/rate-limit keys it actually stores but would corrupt RQ's binary
  data. Same server, same `REDIS_URL`, two connection objects with
  different decode settings.
- `app/models/alert.py` — `Alert`: one row per emergency-tier triage
  decision, `status` (`queued` → `sent`, or `failed`), `message`,
  `recipient_provider_id` (resolved async), timestamps.
- `app/services/alerting.py` — `trigger_high_risk_alert()` runs INLINE in
  the triage request path (one fast INSERT plus an `enqueue()` call,
  wrapped in try/except so an alerting outage can never delay or break an
  emergency response — same principle `app/services/audit_log.py`
  already follows). `process_alert()` is the actual job: resolves an
  on-call recipient (the patient's assigned provider, if any) and marks
  the alert sent. Real notification *delivery* is the next epic
  (Notifications, `docs/phase7f`) — today this proves the decoupled
  pipeline itself works, with a structured log line standing in for an
  actual page.
- `app/api/triage.py` — emergency tier ONLY (not urgent) triggers an
  alert, right after the audit record is logged. `log_triage_decision()`
  was changed to return the new record's id (previously returned
  nothing) so the alert can be linked to it.
- `GET /alerts/recent` — read-only oversight, same panel-based visibility
  as `GET /audit/recent` (reuses `app/services/audit_visibility.py` from
  `docs/phase7d-provider-analytics.md` — a third consumer of that shared
  rule now).

## `ALERTING_SYNC`: not the same pattern as the other test-mode flags

Every other "fake by default in tests" flag in this codebase
(`REDIS_FAKE`, `EMBEDDING_FAKE`, `RATE_LIMIT_ENABLED=0`) exists to skip a
real backing SERVICE the tests don't need. `ALERTING_SYNC=1` (set by
default in `tests/conftest.py`) is different: it runs RQ's `is_async=False`
mode, executing `process_alert()` inline instead of leaving it on a queue
for a separate worker — because unlike Postgres-vs-SQLite or real-vs-fake
Redis, there is genuinely no way to process a real queued job without an
actual `rq worker` process running, and a test suite can't spin one up as
a persistent background process. This makes the flag's meaning closer to
"how is the job executed" than "which backing service." The app's real
default (the flag unset) is the honest one: a real deployment enabling
this feature has a genuine new operational requirement — an `rq worker
high_risk_alerts` process must actually be running, or alerts sit queued
forever.

## Verified live against a real worker process, not just tests

This is the one epic in this project where the "real" path fundamentally
can't be verified by unit tests alone (a test suite can't leave a
background worker running), so it was verified directly against the real
dev server and a real, separate worker process:

1. Started a real, throwaway Redis instance (not the machine's existing
   one — a fresh instance on its own port) and the real FastAPI server
   with `ALERTING_SYNC` unset (the app's real default) and
   `REDIS_URL` pointed at it.
2. Submitted a real emergency-tier triage via `POST /triage/evaluate`.
3. Checked `GET /alerts/recent` immediately — the alert was `status:
   "queued"`, `sent_at: null`. Cross-checked `redis-cli LLEN
   rq:queue:high_risk_alerts` directly — `1`. No worker had run yet; the
   response had already returned to the caller.
4. Started a real `rq.Worker` process (`w.work(burst=True)`) against the
   same Redis instance. Its own log output showed it picking up
   `app.services.alerting.process_alert(1)` and completing it.
5. Re-checked `GET /alerts/recent` — `status: "sent"`, `sent_at`
   populated with a real timestamp from the worker run.

This proves the actual point of the epic: the emergency response doesn't
wait on the alert being processed, and a separate process is what
actually processes it.

## What's still open

- **No real notification delivery** — `process_alert()` resolves a
  recipient and marks the alert sent, but nothing is actually paged
  (SMS/email/push). That's the explicit scope of the next epic
  (Notifications), which this one is a prerequisite for.
- **No retry/dead-letter handling for failed jobs** — RQ supports this
  (failed job registries, retries), but none of it is wired up here; a
  job that raises just fails silently from the alert's perspective (it
  stays `status: "queued"` forever, since `process_alert()` never got to
  update it). A production deployment would want this before relying on
  the queue for anything truly critical.
- **`recipient_provider_id` picks the FIRST assigned provider** when a
  patient has more than one — no on-call rotation, priority, or
  availability logic. A patient with multiple panel providers doesn't
  have a defined "who's actually on call right now" concept yet.
- **No worker process management** — this epic proves the pipeline works
  when a worker runs, but doesn't add any process supervision (systemd
  unit, Docker Compose service, etc.) for actually keeping one alive in a
  real deployment. `docker-compose.yml` would be the natural place to add
  an `rq worker` service alongside the existing `postgres`/`redis`
  entries — not done here.
