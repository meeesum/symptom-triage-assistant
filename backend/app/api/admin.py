"""Admin-only user management — "admin" here means either role that can
manage users: platform-wide "admin" (unrestricted, every org), or
per-tenant "org_admin" (see app/models/user.py). This is what makes role
assignment actually admin-controlled instead of self-service (see
app/api/auth.py's module docstring for the change this replaced). An
admin lists users, finds the one they want to promote, and patches their
role.

Tenant isolation (docs/phase8a-organizations.md): an org_admin only ever
sees/modifies users in their OWN org — both the list and the single-user
PATCH are scoped, not just the list (a PATCH takes an arbitrary user_id
directly, so scoping only the list would leave the mutation endpoint
reachable for a user an org_admin was never shown). An org_admin also
cannot grant "admin" (platform-wide) — that would be a privilege
escalation out of their own tenant, reserved for scripts/create_admin.py.
Platform "admin" is unrestricted in both dimensions, same as before
multi-tenancy existed.

Known limitation: promoting/demoting a user doesn't invalidate their
existing ACCESS token. The JWT's role claim is trusted for the token's
remaining lifetime (up to 1h — see app/core/security.py's
ACCESS_TOKEN_EXPIRY_SECONDS) — see app/api/deps.py's docstring. This
window is narrower than it might look: a user's role is also re-read from
the DB on every refresh-token rotation (see app/services/refresh_tokens.py),
so a session that refreshes picks up the change sooner than a full 1h. A
user who never refreshes (e.g. a short-lived script holding only an
access token) still keeps the old role claim until that token's natural
expiry or explicit revocation. Proactively revoking a user's *other*
active access tokens on a role change isn't possible with the current
blocklist design, since it only tracks jti's that were explicitly
revoked, not a user's set of currently-valid tokens — closing that gap
would need tracking issued (not just revoked) tokens per user, same as
refresh tokens now do (app/models/refresh_token.py), and is real future
work, not done here.

Every role change is recorded in the platform's admin action log (see
app/services/admin_action_log.py and docs/phase8c-admin-action-audit-log.md)
— "who changed which role, when" is the roadmap's own named example for
that epic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, require_role
from app.core.db import get_session
from app.models.admin_action_log import AdminActionLog
from app.models.user import VALID_ROLES, User
from app.services.admin_action_log import list_actions, log_admin_action

router = APIRouter(prefix="/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: int
    email: str
    role: str
    org_id: int


class ActionLogEntry(BaseModel):
    id: int
    actor_id: int
    actor_role: str
    actor_org_id: int
    action: str
    target_type: str
    target_id: str | None
    detail: dict
    created_at: str | None

    @staticmethod
    def from_model(a: AdminActionLog) -> ActionLogEntry:
        return ActionLogEntry(
            id=a.id,
            actor_id=a.actor_id,
            actor_role=a.actor_role,
            actor_org_id=a.actor_org_id,
            action=a.action,
            target_type=a.target_type,
            target_id=a.target_id,
            detail=a.detail,
            created_at=a.created_at.isoformat() if a.created_at else None,
        )


class RoleUpdateRequest(BaseModel):
    role: str


@router.get("/users", response_model=list[UserSummary])
async def list_users(
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> list[UserSummary]:
    with get_session() as session:
        query = select(User).order_by(User.id)
        if admin.role == "org_admin":
            query = query.where(User.org_id == admin.org_id)
        users = session.execute(query).scalars().all()
        return [UserSummary(id=u.id, email=u.email, role=u.role, org_id=u.org_id) for u in users]


@router.patch("/users/{user_id}/role", response_model=UserSummary)
async def update_user_role(
    user_id: int,
    body: RoleUpdateRequest,
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> UserSummary:
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")
    if admin.role == "org_admin" and body.role == "admin":
        raise HTTPException(
            status_code=403, detail="org_admin cannot grant the platform-wide admin role"
        )

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="no such user")
        if admin.role == "org_admin" and user.org_id != admin.org_id:
            # Same existence-hiding judgment as GET /audit/{id}/notes for
            # an out-of-panel record: don't confirm a user outside this
            # org_admin's org even exists.
            raise HTTPException(status_code=404, detail="no such user")

        old_role = user.role
        user.role = body.role
        session.commit()
        session.refresh(user)

        log_admin_action(
            actor_id=admin.id,
            actor_role=admin.role,
            actor_org_id=admin.org_id,
            action="role_change",
            target_type="user",
            target_id=user.id,
            detail={"from_role": old_role, "to_role": user.role},
        )
        return UserSummary(id=user.id, email=user.email, role=user.role, org_id=user.org_id)


@router.get("/action-log", response_model=list[ActionLogEntry])
async def get_action_log(
    limit: int = 100,
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> list[ActionLogEntry]:
    limit = min(max(limit, 1), 200)  # same floor-and-ceiling pattern as GET /audit/recent
    org_id = admin.org_id if admin.role == "org_admin" else None
    return [ActionLogEntry.from_model(a) for a in list_actions(org_id, limit)]
