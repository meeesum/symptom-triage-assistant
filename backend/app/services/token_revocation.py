"""Redis-backed access-token revocation blocklist.

Moved off the `revoked_tokens` SQL table (see
migrations/versions/*_move_token_tracking_to_redis.py) as the second
epic of the scale-up plan's Phase 01 (Production Foundations) — closes
the gap flagged since Phase 4: "every protected request now costs a DB
lookup, which doesn't scale past a prototype."

Each revoked jti is stored as `revoked:{jti}` with a TTL set to exactly
the time remaining until that token's own `exp` claim — once the JWT
would have expired naturally anyway, the blocklist entry is worthless
(the token fails signature/expiry validation regardless of the
blocklist), so Redis's own expiry does the cleanup. This also closes a
second flagged gap for free: the SQL version's docstring noted "no purge
job for expired blocklist rows yet, the table grows unbounded until
then" — there's no equivalent table here to grow.

Kept separate from app/core/security.py deliberately — security.py is
pure crypto (no I/O dependency), which makes its hashing/JWT logic
trivially unit-testable in isolation; revocation is inherently stateful,
so it lives here instead.
"""

from __future__ import annotations

import time

from app.core.redis_client import redis_client

_KEY_PREFIX = "revoked:"


def revoke_token(jti: str, expires_at: int) -> None:
    ttl_seconds = max(1, expires_at - int(time.time()))
    # Idempotent by construction: SET just overwrites if it's already
    # there — logging out twice with the same token is a no-op, not an error.
    redis_client.set(f"{_KEY_PREFIX}{jti}", "1", ex=ttl_seconds)


def is_token_revoked(jti: str) -> bool:
    return bool(redis_client.exists(f"{_KEY_PREFIX}{jti}"))
