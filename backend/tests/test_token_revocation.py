"""Direct unit tests for the Redis-backed access-token blocklist.

Previously only exercised indirectly through the API (test_auth_and_rbac.py's
TestTokenRevocation) — this adds direct coverage of the Redis behavior
itself, including the "self-expiring, no purge job needed" property that's
the actual point of the Redis migration.
"""

import time

from app.core.redis_client import redis_client
from app.services.token_revocation import is_token_revoked, revoke_token


def test_unrevoked_token_is_not_revoked():
    assert is_token_revoked("some-jti-never-revoked") is False


def test_revoked_token_is_revoked():
    jti = "test-jti-revoke-basic"
    revoke_token(jti, expires_at=int(time.time()) + 3600)
    assert is_token_revoked(jti) is True


def test_revoking_twice_is_idempotent():
    jti = "test-jti-revoke-twice"
    revoke_token(jti, expires_at=int(time.time()) + 3600)
    revoke_token(jti, expires_at=int(time.time()) + 3600)  # must not raise
    assert is_token_revoked(jti) is True


def test_revoked_key_has_a_ttl_matching_remaining_token_lifetime():
    # The whole point of moving this to Redis: the blocklist entry expires
    # on its own once the token itself would have expired anyway, instead
    # of needing a separate purge job (the SQL version's flagged gap).
    jti = "test-jti-ttl-check"
    expires_at = int(time.time()) + 120
    revoke_token(jti, expires_at=expires_at)

    ttl = redis_client.ttl(f"revoked:{jti}")
    assert 0 < ttl <= 120


def test_expires_at_in_the_past_still_gets_a_positive_ttl():
    # Defensive floor: an already-expired token being revoked shouldn't
    # compute a zero/negative TTL, which some Redis clients would reject
    # or treat as "no expiry" — the key should still land with a short but
    # positive TTL rather than erroring or persisting forever.
    jti = "test-jti-already-expired"
    revoke_token(jti, expires_at=int(time.time()) - 500)
    ttl = redis_client.ttl(f"revoked:{jti}")
    assert 0 < ttl <= 5
