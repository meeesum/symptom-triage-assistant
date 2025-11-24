"""Session-wide test setup.

Defaults DATABASE_URL to a throwaway SQLite file before any app module is
imported, so running the test suite never writes into the real dev
database (backend/triage_audit.db). Must run before app.core.config /
app.core.db are imported anywhere, which is why this lives in conftest.py
— pytest loads it ahead of test module collection.

Respects an ALREADY-SET DATABASE_URL rather than always overwriting it —
deliberately, so the exact same test suite can be pointed at a real
Postgres instance (`DATABASE_URL=postgresql+psycopg://... pytest`) to
verify the app actually works against Postgres, not just SQLite. An
earlier version of this file unconditionally overwrote DATABASE_URL,
which silently made every "run the tests against Postgres" attempt a
no-op that still ran against SQLite — caught while verifying the Alembic
migration work, not by a test (there wasn't one for this file's own
behavior), which is itself the reason this comment exists.

Schema is created by running the REAL Alembic migrations against
whichever DB is in play (see app/core/migrate.py), not a separate
`Base.metadata.create_all()` path — tests exercising a schema that isn't
what the migration history actually produces would be testing something
that doesn't match what a real deployment runs.

Same "respect an already-set env var, default to a zero-setup local
substitute" pattern applies to Redis: REDIS_FAKE=1 by default, so the
test suite doesn't need a running Redis server any more than it needs a
running Postgres server — see app/core/redis_client.py. Set REDIS_URL
(and unset/skip REDIS_FAKE) to run the suite against a real Redis
instance instead, same as DATABASE_URL for Postgres.

RATE_LIMIT_ENABLED=0 by default for the same reason, but not the same
pattern — this isn't "skip a real backing service," it's a genuine
necessity: starlette's TestClient always presents the same synthetic
remote address, so every test would appear to come from one "IP" and trip
/auth/register's 5/minute limit within the first few tests, throttling
dozens of unrelated tests that just need to register a user. See
app/core/rate_limit.py and tests/test_rate_limiting.py, which explicitly
re-enables it for its own scope to test the limiter itself.

EMBEDDING_FAKE=1 by default for the same reason as REDIS_FAKE — the real
embedding client (app/rag/embeddings.py's FastEmbedClient) downloads a
model from the HF Hub on first use (~15s, one-time, network required); the
deterministic hashed-bag-of-words fake keeps dense-retriever tests fast and
offline by default. Unset it (and set RETRIEVAL_BACKEND=dense) to exercise
the real fastembed + Qdrant path — see tests/test_dense_retriever.py.

ALERTING_SYNC=1 by default — NOT the same pattern as the others above.
Those all skip a real backing SERVICE the tests don't need. This instead
runs the high-risk-alert job queue (app/services/alerting.py) in RQ's
synchronous mode, executing a job inline instead of leaving it queued for
a separate `rq worker` process — because in production, unlike SQLite-vs-
Postgres or fake-vs-real-Redis, there genuinely is no way to process a
real queued job without an actual worker process running, and this test
suite can't spin one up as a persistent background process. Tests that
want to verify the real async path do so directly against a real,
throwaway Redis instance with a real worker — see
docs/phase7e-high-risk-alerting.md.

RETENTION_SYNC=1 by default for the identical reason — mirrors
ALERTING_SYNC for app/services/retention.py's purge job queue. See
docs/phase8d-retention-and-purge-jobs.md.

REPORT_DELIVERY_SYNC=1 by default for the identical reason — mirrors
ALERTING_SYNC/RETENTION_SYNC for app/services/report_delivery.py's
scheduled-report job queue. See docs/phase9d-reporting-exports.md.
"""

import os
import tempfile
from pathlib import Path

if "DATABASE_URL" not in os.environ:
    _tmp_dir = tempfile.mkdtemp(prefix="triage-test-db-")
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp_dir) / 'test_audit.db'}"

if "REDIS_URL" not in os.environ:
    os.environ["REDIS_FAKE"] = "1"

os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("EMBEDDING_FAKE", "1")
os.environ.setdefault("ALERTING_SYNC", "1")
os.environ.setdefault("RETENTION_SYNC", "1")
os.environ.setdefault("REPORT_DELIVERY_SYNC", "1")

if "SYMPTOM_PHOTO_UPLOAD_DIR" not in os.environ:
    # Same "throwaway tmp dir, not the real data/uploads/ tree" pattern as
    # DATABASE_URL above — the test suite writes real files to disk (see
    # app/services/symptom_photos.py), so it needs its own scratch
    # location rather than polluting a real dev deployment's uploads.
    os.environ["SYMPTOM_PHOTO_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="triage-test-uploads-")

from app.core.migrate import run_migrations  # noqa: E402

run_migrations()
