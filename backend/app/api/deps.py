"""Auth dependencies: current-user extraction + role gating.

Deliberately minimal: no per-request DB lookup to confirm the user still
exists (the JWT's role claim is trusted as-is for the token's lifetime —
if an admin changes someone's role, that doesn't take effect until their
current access token expires (1h, see security.py), is explicitly
revoked, or their session refreshes — see app/services/refresh_tokens.py,
which re-reads the role from the DB on every rotation). Revocation itself
IS wired in (see app/services/token_revocation.py) — every request pays a
DB lookup to check the token's `jti` against the blocklist, which is the
tradeoff called out in security.py's docstring.

Only ever validates ACCESS tokens — a refresh token presented here (they
share the same signing key/algorithm) is rejected via the `type` claim
check, so a stolen refresh token can't be used directly as an API
credential.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.services.token_revocation import is_token_revoked

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str
    org_id: int
    jti: str
    exp: int


async def _resolve_current_user(credentials: HTTPAuthorizationCredentials) -> CurrentUser:
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as err:
        raise HTTPException(status_code=401, detail="invalid or expired token") from err

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="not an access token")

    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="token has been revoked")

    return CurrentUser(
        id=int(payload["sub"]),
        role=payload["role"],
        org_id=payload["org_id"],
        jti=jti,
        exp=payload["exp"],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    return await _resolve_current_user(credentials)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser | None:
    """Like get_current_user, but never raises — no token, or an invalid/
    expired/revoked one, just resolves to None (anonymous) rather than a
    401. For routes that work for anyone but behave differently when the
    caller happens to be logged in (see /triage/intake: persists chat
    history for a logged-in patient, stays fully anonymous otherwise)."""
    if credentials is None:
        return None
    try:
        return await _resolve_current_user(credentials)
    except HTTPException:
        return None


def require_role(*allowed_roles: str):
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"requires one of roles: {allowed_roles}")
        return user

    return _check
