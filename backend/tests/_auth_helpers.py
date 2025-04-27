"""Shared test helpers for getting authenticated bearer tokens.

Registration only ever creates patients now (see app/api/auth.py) — role
assignment is admin-controlled. To get a provider/admin token in tests, we
bootstrap one admin account directly in the DB (bypassing the API, same
as scripts/create_admin.py does for real deployments), then use the real
PATCH /admin/users/{id}/role endpoint to promote — so these tests exercise
the actual promotion path, not a shortcut around it.
"""

import itertools

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import get_session
from app.core.security import hash_password
from app.models.user import User
from app.services.organizations import DEFAULT_ORG_SLUG, get_org_by_slug

_email_counter = itertools.count()
_TEST_PASSWORD = "correct-horse-battery-staple"

_bootstrap_admin_token: str | None = None


def _bootstrap_admin(client: TestClient) -> str:
    global _bootstrap_admin_token
    if _bootstrap_admin_token is not None:
        return _bootstrap_admin_token

    email = "bootstrap-admin@example.com"
    with get_session() as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is None:
            default_org = get_org_by_slug(DEFAULT_ORG_SLUG)
            session.add(
                User(
                    email=email,
                    hashed_password=hash_password(_TEST_PASSWORD),
                    role="admin",
                    org_id=default_org.id,
                )
            )
            session.commit()

    r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    assert r.status_code == 200, r.text
    _bootstrap_admin_token = r.json()["access_token"]
    return _bootstrap_admin_token


def _find_user_id(client: TestClient, admin_token: str, email: str) -> int:
    r = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    for u in r.json():
        if u["email"] == email:
            return u["id"]
    raise AssertionError(f"user {email!r} not found in /admin/users")


def register_new_patient(client: TestClient) -> tuple[str, str]:
    """Returns (email, access_token) for a freshly registered patient."""
    email = f"test-user-{next(_email_counter)}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": _TEST_PASSWORD})
    assert r.status_code == 201, r.text
    return email, r.json()["access_token"]


def promote(client: TestClient, email: str, role: str) -> str:
    """Promotes an existing user to `role` via the real admin endpoint and
    returns a fresh token reflecting it (the user's old token still carries
    the pre-promotion role claim until it's refreshed)."""
    admin_token = _bootstrap_admin(client)
    user_id = _find_user_id(client, admin_token, email)
    patch_r = client.patch(
        f"/admin/users/{user_id}/role",
        json={"role": role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch_r.status_code == 200, patch_r.text

    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    assert login_r.status_code == 200, login_r.text
    return login_r.json()["access_token"]


def register_and_get_token(client: TestClient, role: str = "patient") -> str:
    email, token = register_new_patient(client)
    if role == "patient":
        return token
    return promote(client, email, role)


def create_db_user(role: str = "patient", org_id: int | None = None) -> int:
    """Creates a real User row directly in the DB (no HTTP call, no
    token) — for service-level tests (e.g. test_patient_panel_service.py)
    that need a real, valid user id rather than a synthetic int, since
    app/services/patient_panel.py's assign_patient() now looks the user
    up to enforce same-org assignment (docs/phase8a-organizations.md).
    Lands in the default org unless `org_id` is given — most service-level
    tests don't exercise cross-org behavior (that's mostly covered at the
    API layer), but tests/test_cross_phase_contracts.py's org-isolation
    contract tests need real users in TWO distinct orgs, hence the param."""
    email = f"db-user-{next(_email_counter)}@example.com"
    if org_id is None:
        org_id = get_org_by_slug(DEFAULT_ORG_SLUG).id
    with get_session() as session:
        user = User(
            email=email,
            hashed_password=hash_password(_TEST_PASSWORD),
            role=role,
            org_id=org_id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
