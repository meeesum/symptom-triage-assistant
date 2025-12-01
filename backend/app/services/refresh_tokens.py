"""Refresh token issuance, rotation, and reuse detection — Redis-backed.

Rotation: every time a refresh token is used, it's marked used and a
brand-new refresh token is issued to replace it. The old one can never be
used again — this bounds how long a stolen refresh token stays useful to
a single use, rather than being valid for its entire 7-day lifetime.

Reuse detection: if a refresh token that's already been marked used is
presented again, that's a strong signal it was stolen (the legitimate
client already rotated past it) — so ALL of that user's refresh tokens are
revoked immediately, forcing every session (not just the compromised one)
to re-authenticate. This is standard refresh-token-rotation practice, not
something specific to this codebase.

Role (and org_id) are re-read from the User table on every refresh (not
just embedded in the old token) — a nice side effect of not being able to
just re-sign the same claims: a role change via /admin/users/{id}/role
now takes effect the next time that user's session refreshes, not only on
their next full login.
The User lookup itself stays a normal SQL query — only the refresh-token
tracking (issued/used/revoked state) moved to Redis; accounts stay in the
relational DB, which is where they belong.

Atomicity (moved from a SQL `UPDATE ... WHERE used_at IS NULL` — see the
prior version of this file in git history / docs/phase5-postgres-migration.md
for that design — to Redis's `SET key value XX GET`, added in the Redis
migration epic): `XX` means "only set if the key exists," `GET` atomically
returns the value BEFORE this write, and both happen as one indivisible
Redis command. That's the same "claim exactly once under concurrency"
guarantee the SQL version had, expressed with Redis's native primitive
instead of a database transaction — no Lua scripting needed, and it's
exactly as safe under two genuinely concurrent claims of the same token as
the SQL version was (verified with the same concurrency test that caught
the original race — see tests/test_refresh_tokens.py).

Key scheme:
  refresh:{jti}            -> "{user_id}" (unused) or "used:{user_id}" (claimed)
  refresh_by_user:{user_id} -> Redis SET of that user's jtis, for mass
                                revocation on reuse detection (Redis sets
                                don't expire individual members, so this
                                index's own TTL is refreshed on every
                                issue; a stale jti left in it after
                                natural expiry is harmless — deleting an
                                already-gone key is a no-op)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

from app.core.db import get_session
from app.core.redis_client import redis_client
from app.core.security import create_refresh_token, decode_token
from app.models.user import User

_REFRESH_KEY_PREFIX = "refresh:"
_USER_INDEX_PREFIX = "refresh_by_user:"
_USED_MARKER = "used:"


class RefreshTokenInvalid(Exception):
    pass


class RefreshTokenReused(Exception):
    pass


@dataclass(frozen=True)
class RotatedTokens:
    user_id: int
    role: str
    org_id: int
    new_refresh_token: str


def _now() -> int:
    return int(time.time())


def issue_refresh_token(user_id: int) -> str:
    token, jti, expires_at = create_refresh_token(user_id)
    ttl_seconds = max(1, expires_at - _now())

    key = f"{_REFRESH_KEY_PREFIX}{jti}"
    redis_client.set(key, str(user_id), ex=ttl_seconds, nx=True)

    index_key = f"{_USER_INDEX_PREFIX}{user_id}"
    redis_client.sadd(index_key, jti)
    redis_client.expire(index_key, ttl_seconds)  # keeps the index from growing forever

    return token


def revoke_all_refresh_tokens_for_user(user_id: int) -> None:
    """Public since app/services/data_rights.py also needs this — an
    account anonymized by a deletion request must not stay usable via an
    already-issued refresh token for the rest of its 7-day life."""
    index_key = f"{_USER_INDEX_PREFIX}{user_id}"
    jtis = redis_client.smembers(index_key)
    if jtis:
        redis_client.delete(*(f"{_REFRESH_KEY_PREFIX}{jti}" for jti in jtis))
    redis_client.delete(index_key)


def rotate_refresh_token(token_str: str) -> RotatedTokens:
    """Validates + consumes a refresh token, returning the info needed to
    issue a fresh access token plus the new refresh token to replace it.

    Raises RefreshTokenInvalid for any garden-variety invalid token
    (bad signature, expired, wrong type, unknown/revoked, deleted user) and
    RefreshTokenReused specifically for the reuse-detected case, so the API
    layer can log/alert on that differently if it wants to later."""
    try:
        payload = decode_token(token_str)
    except jwt.PyJWTError as err:
        raise RefreshTokenInvalid("invalid or expired refresh token") from err

    if payload.get("type") != "refresh":
        raise RefreshTokenInvalid("not a refresh token")

    jti = payload["jti"]
    user_id = int(payload["sub"])
    key = f"{_REFRESH_KEY_PREFIX}{jti}"

    # Atomic claim — see module docstring. `xx` only writes if the key
    # exists; `get` atomically returns the value from BEFORE this write.
    ttl_seconds = max(1, int(payload["exp"]) - _now())
    old_value = redis_client.set(key, f"{_USED_MARKER}{user_id}", ex=ttl_seconds, xx=True, get=True)

    if old_value is None:
        raise RefreshTokenInvalid("unknown, expired, or revoked refresh token")

    if old_value.startswith(_USED_MARKER):
        revoke_all_refresh_tokens_for_user(user_id)
        raise RefreshTokenReused("refresh token reuse detected; all sessions revoked")

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise RefreshTokenInvalid("user no longer exists")
        role = user.role
        org_id = user.org_id

    new_refresh_token = issue_refresh_token(user_id)
    return RotatedTokens(
        user_id=user_id, role=role, org_id=org_id, new_refresh_token=new_refresh_token
    )


def revoke_refresh_token(token_str: str) -> None:
    """Best-effort revoke for logout — an already-invalid/garbage token is
    simply ignored rather than raising, since logout should never fail."""
    try:
        payload = decode_token(token_str)
    except jwt.PyJWTError:
        return
    if payload.get("type") != "refresh":
        return

    jti = payload["jti"]
    user_id = payload["sub"]
    redis_client.delete(f"{_REFRESH_KEY_PREFIX}{jti}")
    redis_client.srem(f"{_USER_INDEX_PREFIX}{user_id}", jti)
