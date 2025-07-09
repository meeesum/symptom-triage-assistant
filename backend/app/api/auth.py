"""Registration, login, logout, and token refresh.

`/auth/register` always creates a `patient` account — self-service role
selection (previously allowed here) was removed. Role assignment is now
admin-controlled: an existing admin promotes a user via
`PATCH /admin/users/{id}/role` (see app/api/admin.py). The very first
admin account has to come from somewhere other than the API, since there's
no admin yet to promote anyone — see scripts/create_admin.py for that
one-time bootstrap.

Every successful register/login/refresh returns BOTH an access token
(short-lived, 1h — what you send as the Bearer credential on every
request) and a refresh token (long-lived, 7d — sent only to
`POST /auth/refresh` to get a new access token without re-entering a
password). See app/services/refresh_tokens.py for rotation and reuse
detection.

Rate limited per-IP (see app/core/rate_limit.py): register 5/min, login
10/min, refresh 30/min — narrow, endpoint-specific limits on the routes
where abuse has an obvious concrete cost (credential stuffing, mass
account creation), not a blanket limit across the whole API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.services.organizations import DEFAULT_ORG_SLUG, get_org_by_slug
from app.services.refresh_tokens import (
    RefreshTokenInvalid,
    RefreshTokenReused,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.services.token_revocation import revoke_token

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr = Field(examples=["patient@example.com"])
    password: str = Field(min_length=8, examples=["correct-horse-battery-staple"])
    org_slug: str | None = Field(
        default=None,
        description=(
            "Which organization to join. Omit to join the zero-setup default "
            "organization — see app/services/organizations.py and "
            "docs/phase8a-organizations.md."
        ),
    )


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["patient@example.com"])
    password: str = Field(examples=["correct-horse-battery-staple"])


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


def _issue_token_pair(user: User) -> TokenResponse:
    access_token = create_access_token(user_id=user.id, role=user.role, org_id=user.org_id)
    refresh_token = issue_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role=user.role)


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest) -> TokenResponse:
    org_slug = body.org_slug or DEFAULT_ORG_SLUG
    org = get_org_by_slug(org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail=f"no organization with slug {org_slug!r}")

    with get_session() as session:
        existing = session.execute(
            select(User).where(User.email == body.email)
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="an account with this email already exists")

        user = User(
            email=body.email,
            hashed_password=hash_password(body.password),
            role="patient",
            org_id=org.id,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError as err:
            # The existence check above is a TOCTOU race, not a real
            # guarantee — two concurrent registrations with the same email
            # can both pass it before either commits. User.email is
            # unique=True, so the second commit hits that constraint; catch
            # it here and turn it into the same clean 409 the check above
            # was trying to produce, instead of an unhandled 500.
            session.rollback()
            raise HTTPException(
                status_code=409, detail="an account with this email already exists"
            ) from err
        session.refresh(user)

        return _issue_token_pair(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest) -> TokenResponse:
    with get_session() as session:
        user = session.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
        if user is None or not verify_password(body.password, user.hashed_password):
            # Same error for "no such user" and "wrong password" — don't leak
            # which one it was, that's an account-enumeration vector.
            raise HTTPException(status_code=401, detail="invalid email or password")

        return _issue_token_pair(user)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, body: RefreshRequest) -> TokenResponse:
    try:
        rotated = rotate_refresh_token(body.refresh_token)
    except RefreshTokenReused:
        # Deliberately the same 401 shape as a garden-variety invalid
        # token — don't hand an attacker a distinct signal that they
        # tripped reuse detection specifically. `from None` is also
        # deliberate: this is a fresh HTTP-layer error, not a wrapper
        # around the internal exception, and the client shouldn't see
        # RefreshTokenReused's traceback chained onto it.
        raise HTTPException(status_code=401, detail="invalid or expired refresh token") from None
    except RefreshTokenInvalid as err:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token") from err

    access_token = create_access_token(
        user_id=rotated.user_id, role=rotated.role, org_id=rotated.org_id
    )
    return TokenResponse(
        access_token=access_token, refresh_token=rotated.new_refresh_token, role=rotated.role
    )


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    """Revokes the presented access token so it stops working immediately
    (rather than remaining valid until its natural 1h expiry), and — if a
    refresh token is included in the body — revokes that too, so the
    client can't silently mint a new access token right after "logging
    out". The refresh token is optional because not every caller of this
    endpoint necessarily has one handy (e.g. an access-token-only client)."""
    revoke_token(current_user.jti, current_user.exp)
    if body is not None and body.refresh_token:
        revoke_refresh_token(body.refresh_token)
