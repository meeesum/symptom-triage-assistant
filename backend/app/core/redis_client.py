"""Redis client — module-level singleton, same pattern as `engine` in
app/core/db.py: created once at import time, not per-call.

Two modes, matching this project's established dual-mode pattern (SQLite/
Postgres, TF-IDF/dense-embeddings):

  - Real Redis (default) — REDIS_URL env var, defaults to a local instance
    for dev (see docker-compose.yml).
  - `fakeredis` (REDIS_FAKE=1) — an in-memory, pure-Python Redis
    implementation used by the test suite so `pip install -r
    requirements.txt && pytest` still needs zero external services, the
    same guarantee the SQLite bootstrap gives for Postgres. tests/conftest.py
    sets REDIS_FAKE=1 before any app module is imported.

Both implement the same command surface this project actually uses
(SET with NX/XX/GET/EX, GET, DEL, SMEMBERS, SADD, EXISTS), so
app/services/token_revocation.py and app/services/refresh_tokens.py don't
need to know or care which one they're talking to.
"""

from __future__ import annotations

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

if os.environ.get("REDIS_FAKE") == "1":
    import fakeredis

    redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
else:
    import redis

    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
