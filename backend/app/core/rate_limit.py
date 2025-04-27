"""Rate limiting — fourth epic of Phase 01 (API hardening).

Backed by the SAME Redis instance as token tracking when a real one is
configured, so rate-limit counters survive an app restart and are shared
correctly across multiple app instances (an in-process counter would
reset on redeploy and wouldn't work at all behind more than one replica).
Falls back to an in-process (`memory://`) limiter store under
`REDIS_FAKE=1` — fakeredis is an in-memory Python object, not something
reachable via a `redis://` URL, so the `slowapi`/`limits` library can't
point at it directly; the in-memory fallback keeps the test suite's
zero-setup guarantee intact (same pattern as every other Redis/Postgres
default in this project) while still exercising the real rate-limiting
logic, just with per-process rather than shared storage.

Applied narrowly, not globally: only on the endpoints where abuse actually
has a concrete cost (`/auth/login`, `/auth/register`, `/auth/refresh` —
brute-forcing a password, mass-registering accounts, or hammering token
rotation). The triage endpoints stay unlimited for now since they're the
product's core anonymous-use path and a blanket limit there needs product
input on what a legitimate usage pattern looks like, not an engineering
default guessed at here.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.redis_client import REDIS_URL

_storage_uri = "memory://" if os.environ.get("REDIS_FAKE") == "1" else REDIS_URL

# Disabled by default under tests (conftest.py sets RATE_LIMIT_ENABLED=0) —
# not a test-suite-specific carve-out done for convenience, but a real
# necessity: starlette's TestClient always presents the same synthetic
# remote address, so every test in the suite would appear to come from one
# "IP" and exhaust the /auth/register limit within the first handful of
# tests, throttling dozens of unrelated tests that just need to register a
# user. Dedicated rate-limiting tests (tests/test_rate_limiting.py)
# explicitly flip `limiter.enabled = True` for their own scope instead.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "1") == "1",
)
