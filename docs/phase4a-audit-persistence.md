# Phase 4 deep-dive: persistent audit logging

## What's built

- `app/core/config.py` — `DATABASE_URL`, defaulting to a local SQLite file
  (`backend/triage_audit.db`), overridable via env var.
- `app/core/db.py` — SQLAlchemy engine/session setup, `init_db()` (creates
  tables if missing), and `get_session()` as a context manager. Tables are
  created eagerly at import time, not only via the FastAPI startup event —
  needed because `starlette.testclient.TestClient` doesn't reliably fire
  lifespan events unless used as a context manager, and the previous stub
  had no persistence to notice this with.
- `app/models/audit.py` — `TriageAuditRecord`: symptom_ids, severity,
  onset, a truncated free-text excerpt, tier, matched_rule_id,
  requires_human_review, decision_source, created_at.
- `app/services/audit_log.py` — now writes to both stdout (as before) and
  the DB table. The DB write is wrapped in try/except: a DB outage
  degrades to stdout-only rather than ever blocking or failing a triage
  response. That failure is logged at ERROR level, not swallowed silently.
- `app/api/audit.py` — `GET /audit/recent` (capped at 200, default 50),
  the first real consumer of the audit trail, and the seed of the future
  Phase 4 provider dashboard.
- `backend/tests/conftest.py` — points `DATABASE_URL` at a throwaway
  temp-file SQLite DB before any app module is imported, so running the
  test suite never touches the real dev DB file (`backend/triage_audit.db`).

## Why SQLite, why eager table creation, why no auth yet

**SQLite** is the same kind of deliberate bootstrap choice as TF-IDF
retrieval in Phase 1: zero external service dependency, runs anywhere
`pip install` runs, good enough to prove the audit-trail shape end to end.
It is explicitly **not** the production target — no concurrent-write
story, no managed backups, no retention policy. `requirements.txt` already
has `psycopg2-binary`/`alembic` as commented-out next steps for the
Postgres migration.

**Eager `init_db()` at import time** (not only via FastAPI's lifespan
hook) exists because of a concrete bug this session ran into: `TestClient`
in newer Starlette versions doesn't fire startup/shutdown events unless
used as `with TestClient(app) as client:`, and the existing test files use
the bare `TestClient(app)` form. Without eager creation, tests would have
silently hit "no such table" — caught by `audit_log.py`'s try/except and
logged as an ERROR, but never surfaced as a test failure, which is exactly
the kind of silent gap this project has been trying not to leave. Calling
`init_db()` at module import removes the dependency on lifespan timing
entirely.

**`GET /audit/recent` has no auth.** This is called out directly in the
route's docstring and here, not left implicit: it exists to prove the
audit trail has a real reader, and to be the seed of the provider
dashboard — not to be an open production endpoint. It also deliberately
excludes `free_text_excerpt` from its response (verified by
`test_triage_decision_appears_in_audit_recent`), even though the excerpt
is stored, as a small privacy default until real auth/RBAC lands.

## What's still open

- Auth/RBAC on `/audit/recent` (explicitly deferred — this is the
  remaining core piece of Phase 4)
- Retention policy / encryption for `free_text_excerpt` before any real
  patient data reaches this table
- Postgres migration + Alembic migrations for concurrent-write safety at
  real scale
- A provider-facing UI consuming this endpoint (currently API-only)
