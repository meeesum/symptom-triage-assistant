# Phase 5 deep-dive: Postgres + Alembic migrations

First epic of the scale-up roadmap's Phase 01 (Production Foundations) —
see the published roadmap artifact for the full six-phase plan. This
closes the SQLite bootstrap-choice note that's been sitting in
`app/core/config.py` and `app/core/db.py` since Phase 4.

## What's built

- `alembic.ini` + `migrations/` — a real Alembic setup. `migrations/env.py`
  imports `Base` and every model module (so `target_metadata` actually
  sees all five tables) and sets its DB URL from `DATABASE_URL` — the same
  env var `app/core/config.py` reads — rather than a second hardcoded URL
  in `alembic.ini` that could drift out of sync.
- `migrations/versions/340bba4518b7_initial_schema.py` — the initial
  migration, generated via `alembic revision --autogenerate` against an
  empty DB and diffed against the current five models (`users`,
  `triage_audit_records`, `refresh_tokens`, `revoked_tokens`,
  `chat_exchanges`).
- `app/core/migrate.py` — `run_migrations()`, the one place schema changes
  actually get applied. Deliberately separate from `app/core/db.py`: the
  old `db.py` had `Base.metadata.create_all()` running as a side effect of
  being *imported* (see the Phase 4 docs) — the same pattern here would
  mean importing `db.py` from inside `migrations/env.py` (to get `Base`)
  recursively triggers a migration run. `db.py` is now just engine/session/
  `Base` with zero import-time side effects.
- `scripts/migrate.py` — CLI entry point for running migrations as an
  explicit deploy step (the production pattern: run once, before starting
  any app instance — see its docstring for why auto-migrating on every
  boot is the wrong default once there's more than one replica).
- `docker-compose.yml` — local Postgres for dev, matching the DB target a
  real deployment would actually use instead of the SQLite bootstrap.

## Why psycopg v3, not psycopg2

The original plan (and the commented-out dependency this project has
carried since Phase 4) was `psycopg2-binary`. It doesn't have a prebuilt
wheel for Python 3.13 on this machine, and building it from source fails:
`psycopg2`'s C extension calls `_PyInterpreterState_Get()`, a private
CPython API that Python 3.13 removed. Rather than pin an older Python or
patch a C extension, this switched to `psycopg` (v3) — actively
maintained, ships real wheels for 3.13, and SQLAlchemy 2.0 supports it
natively via the `postgresql+psycopg` dialect (distinct from
`postgresql+psycopg2` — the driver segment in the URL matters).

## Why SQLite stays the default, not Postgres

A fresh clone still runs with zero setup — `pip install -r
requirements.txt && uvicorn app.main:app` — no DB server required. That
matters for a project whose whole ethos has been "never undemoable."
Postgres is one `DATABASE_URL` env var and (optionally) `docker-compose
up` away, not a hard requirement to even boot the app. What changed is
that now BOTH SQLite and Postgres run off the exact same Alembic
migration history, instead of SQLite getting `create_all()`'s ad-hoc
schema and Postgres getting whatever `create_all()` would produce there
too (untested, since nothing had ever actually run against Postgres).

## Verified, not just assumed

This is the part worth being explicit about: "SQLAlchemy is
database-agnostic" is a claim, not a guarantee, and the previous state of
this codebase had never once run against a real Postgres instance. To
verify:

1. Initialized a fresh, throwaway Postgres 16 data directory (not the
   machine's existing Homebrew Postgres cluster — this was scoped
   entirely to a temp directory, started on a non-default port, and torn
   down afterward).
2. Ran `run_migrations()` against it directly — confirmed the exact same
   migration that built the SQLite schema also builds a correctly-typed
   Postgres schema (`timestamp with time zone`, proper `SERIAL`-backed
   `nextval()` sequences, the unique index on `refresh_tokens.jti`, etc —
   inspected via `psql \d`).
3. Ran the **entire backend test suite** (128 tests) against that
   Postgres instance, not SQLite — required fixing a real bug in the
   process: `tests/conftest.py` was unconditionally overwriting
   `DATABASE_URL` with a throwaway SQLite path, which meant every
   previous attempt to point the suite at Postgres would have silently
   still run against SQLite. Fixed to only default `DATABASE_URL` when
   it isn't already set.
4. Confirmed by inspecting Postgres directly after the run — real rows
   existed in `users`, `triage_audit_records`, and `refresh_tokens`
   (39/15/66 respectively), proving the app was actually writing there,
   not silently falling back to something else.

## What's still open (rest of Phase 01)

- Redis-backed token tracking (next epic — the DB-backed blocklist/
  refresh-token tables still work under Postgres, but still cost a SQL
  round-trip per protected request, same tradeoff flagged since Phase 4)
- Structured logging, Sentry, CI, Dockerfiles
- Rate limiting + OpenAPI enrichment
- `docker-compose.yml` is provided but unverified in this sandbox
  specifically (no Docker available here) — the underlying mechanism
  (Alembic + psycopg3 + Postgres) was verified directly against a real
  `postgres` binary instead, which is the part that was actually in
  question.
