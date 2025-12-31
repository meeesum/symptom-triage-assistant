"""Password hashing + JWT issuance/verification.

Bootstrap choices, same pattern as TF-IDF (Phase 1) and SQLite (Phase 4
audit): good enough to prove auth/RBAC works end to end, explicitly not
production-hardened.

- Password hashing uses PBKDF2-HMAC-SHA256 via the stdlib `hashlib`
  (no bcrypt/argon2 dependency) — fine for a prototype, but a real
  deployment should move to a maintained library (passlib+argon2 or
  bcrypt) that tracks parameter recommendations over time; a hand-rolled
  scheme frozen at whatever iteration count seemed reasonable today will
  not age well.
- JWT secret defaults to an insecure dev value and MUST be overridden via
  the SECRET_KEY env var before this is ever exposed outside localhost —
  enforced by `_require_non_default_secret_in_prod` below, not just a
  comment.
- Revocation is a Redis-backed blocklist of token IDs (`jti`), checked on
  every request — see app/services/token_revocation.py and app/api/deps.py.
  Moved off a SQL table (see docs/phase5-postgres-migration.md) to a
  self-expiring Redis key, closing the "costs a DB lookup on every
  request" and "no purge job" gaps this same paragraph used to flag.
- Access tokens are now short-lived (1h, down from the original 24h) with
  a refresh-token flow (see create_refresh_token / app/services/refresh_tokens.py)
  to get a new one without re-entering a password. Shortening the access
  token lifetime also narrows an existing gap: a role change via
  /admin/users/{id}/role doesn't invalidate a user's already-issued
  token, so it now takes at most 1h (not 24h) for a demoted user's old
  permissions to actually expire on their own.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import jwt

_PBKDF2_ITERATIONS = 260_000
_PBKDF2_ALGORITHM = "sha256"

_DEV_DEFAULT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60          # 1 hour
REFRESH_TOKEN_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _require_non_default_secret_in_prod() -> None:
    if os.environ.get("ENVIRONMENT") == "production" and SECRET_KEY == _DEV_DEFAULT_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the insecure dev default while ENVIRONMENT=production. "
            "Set a real SECRET_KEY before starting the server."
        )


_require_non_default_secret_in_prod()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        salt, digest_hex = hashed.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(expected.hex(), digest_hex)


def create_access_token(user_id: int, role: str, org_id: int) -> str:
    payload = {
        "type": "access",
        "sub": str(user_id),
        "role": role,
        "org_id": org_id,  # trusted for the token's lifetime, same as role — see deps.py
        "jti": secrets.token_hex(16),  # unique per token — what revocation targets
        "exp": int(time.time()) + ACCESS_TOKEN_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, int]:
    """Returns (token_string, jti, expires_at_unix). The jti/expiry are
    returned separately (not just embedded in the token) because the
    caller (app/services/refresh_tokens.py) needs them to record the
    token server-side — refresh tokens are tracked by issuance, not just
    by revocation, so a presented token can be checked against "was this
    actually issued and not yet used/revoked" rather than just "is this
    signature valid" (a valid signature alone doesn't rule out a stolen,
    already-rotated-out token — see refresh_tokens.py for reuse detection).
    """
    jti = secrets.token_hex(16)
    expires_at = int(time.time()) + REFRESH_TOKEN_EXPIRY_SECONDS
    payload = {"type": "refresh", "sub": str(user_id), "jti": jti, "exp": expires_at}
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired token —
    callers are expected to catch that and turn it into a 401. Does NOT
    check the `type` claim — callers that care whether it's an access or
    refresh token (all of them) must check payload["type"] themselves."""
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
