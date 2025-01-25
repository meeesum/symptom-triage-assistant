# Phase 5c deep-dive: observability & CI

Third epic of the scale-up roadmap's Phase 01 (Production Foundations),
following `docs/phase5-postgres-migration.md` and
`docs/phase5b-redis-token-tracking.md`.

## What's built

- `app/core/logging_config.py` — wraps stdlib `logging` with `structlog`
  rather than replacing the codebase's one existing `logging.getLogger`
  call site (`audit_log.py`). Anything that reaches for stdlib logging in
  the future — the obvious default — gets structured output for free.
  JSON lines when `ENVIRONMENT=production` (or `LOG_FORMAT=json`
  explicitly), a human-readable colored console renderer otherwise.
  uvicorn's own loggers are routed through the same handler so they don't
  bypass it and print unstructured lines alongside everything else.
- `app/core/sentry.py` — opt-in via `SENTRY_DSN`; a genuine no-op when
  unset (this sandbox has no real Sentry project to report to). Explicitly
  sets `send_default_pii=False` — this app handles real patient-adjacent
  text, so PII reporting is something to opt into deliberately, not
  something a library default should decide.
- `app/api/health.py` — `GET /health/ready`, distinct from the existing
  `GET /health`. Liveness (`/health`) only proves the process answers
  HTTP; readiness additionally checks the DB and Redis are actually
  reachable, and returns a real `503` (not just a JSON field) when they
  aren't — an orchestrator's readiness probe checks the HTTP status code,
  and conflating the two checks is a classic mistake (an instance that's
  alive but can't reach its DB should stop receiving traffic, not get
  killed and restarted, which won't fix an external outage).
- `backend/Dockerfile`, `frontend/Dockerfile` — multi-stage builds for
  both services. The frontend's uses Next.js's `output: "standalone"`
  (added to `next.config.js`) so the shipped image carries only the
  traced production dependency subset, not the full `node_modules` tree.
- `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`
  — lint + test on every push/PR touching each service. The backend
  workflow runs the suite TWICE: once against the zero-setup SQLite +
  fakeredis default (same as a fresh local clone), and once against real
  Postgres + Redis service containers — specifically because the
  zero-setup default can't catch the class of bug the Postgres/Redis
  migration work already found once (the `conftest.py` `DATABASE_URL`
  overwrite bug from `docs/phase5-postgres-migration.md`). CI is scoped
  to actually catch that again if it ever regresses, not just prove the
  happy path.

## Closing a real gap the new lint scope surfaced

Wiring `ruff` into CI meant actually running it — which, with the default
`[E, F]` rule set this project already had, was clean, but expanding to
`[E, F, W, B, UP, SIM, G]` (the rule categories that actually catch real
issues: bugbear, pyupgrade, simplify, logging) surfaced 33 findings across
the existing codebase, not just new code from this phase. All were fixed
before wiring lint into CI — shipping a CI pipeline that's red on day one
teaches everyone to ignore it. Two were judgment calls, not blind fixes:

- **`B008` (FastAPI's `Depends(...)` in argument defaults) — ignored
  project-wide**, not fixed. This is FastAPI's own correct
  dependency-injection idiom, used at ~13 call sites throughout `app/api/`
  — the lint rule doesn't know about the framework's pattern, and noqa'ing
  13 identical call sites would be worse than one documented project-wide
  ignore in `pyproject.toml`.
- **`BLE001` (catching blind `Exception`) in `app/api/health.py`'s two
  checks — kept, with an inline `noqa` and a one-line reason.** A
  readiness check needs to report `False` on ANY failure mode, not crash
  the endpoint — this is the one place in the codebase where catching
  `Exception` broadly is the *correct* behavior, not an oversight.

Also excluded: `migrations/versions/*` from linting entirely. Those files
are Alembic-generated, not hand-authored, and "fixing" style findings in
an already-applied, already-verified migration risks quietly changing
what it does. New migrations are still reviewed by hand before commit —
just not held to this project's general style rules (autogenerate's own
output conventions, like `Union[...]` instead of `X | None`, are what
they are).

## What's still open

- No log aggregation destination configured (stdout only) — fine for
  `docker logs`/local dev, a real deployment would ship these to
  something (CloudWatch, Datadog, etc.), which is an infra decision this
  phase deliberately doesn't make.
- Both Dockerfiles are unverified in this sandbox specifically (no Docker
  available here) — same caveat as `docker-compose.yml`'s postgres/redis
  services. The frontend's `output: "standalone"` build WAS verified
  directly (`npm run build`, confirmed `.next/standalone/server.js` and
  its trimmed `node_modules` actually exist) since that's the part a
  Dockerfile alone couldn't prove.
- CI workflows are YAML-validated (parsed successfully) but not run
  end-to-end against a real GitHub Actions runner from this environment —
  the commands they run (`ruff check .`, `pytest -q` against real
  Postgres/Redis, `tsc --noEmit`, `npm run build`) were each verified to
  actually work locally first.
