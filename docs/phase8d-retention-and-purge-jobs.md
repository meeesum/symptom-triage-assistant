# Phase 8d deep-dive: retention & purge jobs

Fourth and final epic of the scale-up roadmap's Phase 04 (Multi-Tenancy &
Compliance) — depending on "High-risk alerting + job queue"
(`docs/phase7e-high-risk-alerting.md`), which is the actual queue
infrastructure this epic reuses. **With this, Phase 04 is complete, and
this is the last Phase 04 epic in the scale-up roadmap.**

## Half the roadmap's own gap was already closed — said honestly, not silently reused

The roadmap named this epic as closing "the 'no purge job yet' gap
flagged on the revoked-token and refresh-token tables, plus a
configurable retention window for chat history and audit records." The
first half doesn't apply anymore: `docs/phase5b-redis-token-tracking.md`
(Phase 01) already moved both to self-expiring Redis keys specifically so
no purge job would ever be needed for them — a TTL, not a table. Building
a purge job for tables that no longer exist would be pointless; silently
skipping the roadmap's own words without explaining why would look like
an oversight. This epic's real scope is the second half: configurable
retention for chat history and audit records — plus, since
`docs/phase8c-admin-action-audit-log.md` flagged its own log as having
"no retention policy... itself," that gets a window too.

## What's built

- `app/services/retention.py` — `purge_old_data()`: deletes
  `ChatExchange` rows older than `CHAT_HISTORY_RETENTION_DAYS` (default
  90), `TriageAuditRecord` rows older than `AUDIT_RECORD_RETENTION_DAYS`
  (default 365), and `AdminActionLog` rows older than
  `ADMIN_ACTION_LOG_RETENTION_DAYS` (default 365) — each independently
  configurable via env var. Genuine deletion, not anonymization: unlike
  `app/services/data_rights.py`'s "delete my data" (a specific
  individual's rights request, answered right now), a retention policy's
  whole point is that data eventually goes away entirely once its window
  passes, for everyone, on a schedule — a different concern.
- `app/models/retention_purge_run.py` — `RetentionPurgeRun`: one row per
  purge run, recording exactly what got deleted. Same "a log that could
  be silently skipped isn't a log" instinct as `AdminActionLog` — "did
  the purge actually run, and how much did it delete" should always be
  answerable, not just trusted.
- **Reuses the exact job-queue infrastructure from
  `docs/phase7e-high-risk-alerting.md`** (RQ, `app/core/queue_client.py`)
  — this is the roadmap's own named dependency actually being used, not
  just referenced. `RETENTION_SYNC` mirrors `ALERTING_SYNC` exactly: `1`
  by default in tests (inline execution, no worker needed), unset by
  default in the real app (genuine async queueing, needs a real `rq
  worker retention` process).
- `scripts/run_retention_purge.py` — the REALISTIC trigger for a real
  deployment: an external cron entry running this script on a schedule,
  same "not something the app quietly does on its own" judgment as
  `app/core/migrate.py`/`scripts/migrate.py`.
- `POST /admin/retention/purge` + `GET /admin/retention/runs` —
  manually-triggerable + oversight, for testing/ops visibility rather
  than as the primary trigger. Platform `admin` only, deliberately NOT
  `org_admin`: retention is a platform-wide data-lifecycle operation
  (chat history and audit records age out on the same global clock
  regardless of org), not a per-tenant one.

## Verified live, not just tests

1. Seeded real rows directly in the DB: a 200-day-old chat exchange and a
   1-day-old one; a 500-day-old audit record and a fresh one.
2. Ran the real `scripts/run_retention_purge.py` cron script (no server,
   no mocking) — output: `"1 chat exchange(s), 1 audit record(s), 0
   admin action log(s) deleted."`
3. Queried the DB directly afterward: only the recent chat exchange and
   the recent audit record remained — the old ones were genuinely gone,
   the new ones untouched.
4. Separately, `POST /admin/retention/purge` against the real running
   server (with the app's actual async default, `RETENTION_SYNC` unset)
   returned `{"status": "enqueued"}` and — correctly — did NOT
   immediately show up in `GET /admin/retention/runs` (still showing only
   the earlier cron-script run), confirming the job genuinely stayed
   queued rather than running inline. The queue mechanism itself (a real
   `rq worker` actually picking up and completing a queued job) was
   already proven end-to-end with a real worker process in
   `docs/phase7e-high-risk-alerting.md`, using this exact same RQ +
   `queue_client.py` plumbing — re-running that same proof for a second
   job type would just repeat it, not add new evidence.

## What's still open

- **No per-org retention windows** — every organization shares the same
  global retention config. A real multi-tenant deployment might want
  different windows per org (e.g. a clinic under a longer regulatory
  retention requirement than another) — not built here, a reasonable
  future upgrade once there's a real need for it.
- **No dry-run mode** — `purge_old_data()` deletes immediately; there's
  no way to preview what a purge WOULD delete before committing to it.
- **No actual scheduling mechanism ships with this repo** — this epic
  builds the job and the script; making it actually run on a schedule
  needs a real external cron entry (or equivalent) in whatever
  environment deploys this, same as `docker-compose.yml` needing an
  actual `rq worker` service added for the alerting epic
  (`docs/phase7e-high-risk-alerting.md`'s own open item) — neither is
  done here.
- **Alerts and referrals aren't covered by retention** — only chat
  history, audit records, and the admin action log. Those two tables
  (and consent/data-request records, which have their own compliance
  purpose) were deliberately left out of scope; worth a second look if
  they turn out to need their own windows later.
