"""API-level tenant-isolation tests. See app/api/organizations.py,
app/api/auth.py's org_slug support, app/api/admin.py's org_admin
scoping, app/api/patient_panel.py's cross-org rejection, and
docs/phase8a-organizations.md.
"""

import itertools

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token

client = TestClient(app)

_slug_counter = itertools.count()


def _signup_org() -> tuple[str, str, str]:
    """Returns (slug, admin_email, admin_token) for a freshly created org."""
    n = next(_slug_counter)
    slug = f"tenant-{n}"
    admin_email = f"orgadmin-{n}@example.com"
    r = client.post(
        "/organizations",
        json={
            "name": f"Tenant {n}",
            "slug": slug,
            "admin_email": admin_email,
            "admin_password": "correct-horse-battery-staple",
        },
    )
    assert r.status_code == 201, r.text

    login_r = client.post(
        "/auth/login", json={"email": admin_email, "password": "correct-horse-battery-staple"}
    )
    assert login_r.status_code == 200, login_r.text
    return slug, admin_email, login_r.json()["access_token"]


def _register_in_org(slug: str) -> tuple[str, str]:
    n = next(_slug_counter)
    email = f"member-{n}@example.com"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-battery-staple", "org_slug": slug},
    )
    assert r.status_code == 201, r.text
    return email, r.json()["access_token"]


def test_register_without_org_slug_joins_default_org():
    n = next(_slug_counter)
    email = f"no-org-slug-{n}@example.com"
    r = client.post(
        "/auth/register", json={"email": email, "password": "correct-horse-battery-staple"}
    )
    assert r.status_code == 201, r.text

    platform_admin_token = register_and_get_token(client, role="admin")
    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {platform_admin_token}"}
    ).json()
    new_user = next(u for u in users if u["email"] == email)
    default_org_admin = next(u for u in users if u["email"] == "bootstrap-admin@example.com")
    assert new_user["org_id"] == default_org_admin["org_id"]


def test_register_with_unknown_org_slug_returns_404():
    r = client.post(
        "/auth/register",
        json={
            "email": "nobody@example.com",
            "password": "correct-horse-battery-staple",
            "org_slug": "no-such-tenant-slug",
        },
    )
    assert r.status_code == 404


def test_organization_signup_creates_a_working_org_admin_account():
    slug, admin_email, admin_token = _signup_org()
    r = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert admin_email in emails


def test_duplicate_org_slug_returns_409():
    n = next(_slug_counter)
    slug = f"dup-tenant-{n}"
    body = {
        "name": "X",
        "slug": slug,
        "admin_email": f"a-{n}@example.com",
        "admin_password": "correct-horse-battery-staple",
    }
    r1 = client.post("/organizations", json=body)
    assert r1.status_code == 201
    body["admin_email"] = f"b-{n}@example.com"
    r2 = client.post("/organizations", json=body)
    assert r2.status_code == 409


def test_org_admin_only_sees_users_in_their_own_org():
    slug_a, admin_a_email, admin_a_token = _signup_org()
    slug_b, admin_b_email, admin_b_token = _signup_org()
    member_a_email, _ = _register_in_org(slug_a)
    member_b_email, _ = _register_in_org(slug_b)

    r = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_a_token}"})
    emails = [u["email"] for u in r.json()]
    assert admin_a_email in emails
    assert member_a_email in emails
    assert admin_b_email not in emails
    assert member_b_email not in emails


def test_org_admin_cannot_promote_a_user_to_platform_admin():
    slug, _admin_email, admin_token = _signup_org()
    member_email, _ = _register_in_org(slug)

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    member_id = next(u["id"] for u in users if u["email"] == member_email)

    r = client.patch(
        f"/admin/users/{member_id}/role",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 403


def test_org_admin_cannot_modify_a_user_in_another_org():
    slug_a, _e1, admin_a_token = _signup_org()
    slug_b, _e2, _admin_b_token = _signup_org()
    member_b_email, _ = _register_in_org(slug_b)

    platform_admin_token = register_and_get_token(client, role="admin")
    all_users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {platform_admin_token}"}
    ).json()
    member_b_id = next(u["id"] for u in all_users if u["email"] == member_b_email)

    r = client.patch(
        f"/admin/users/{member_b_id}/role",
        json={"role": "provider"},
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert r.status_code == 404  # existence-hidden, not 403 — see app/api/admin.py


def test_platform_admin_sees_and_manages_every_org():
    slug, _admin_email, _admin_token = _signup_org()
    member_email, _ = _register_in_org(slug)

    platform_admin_token = register_and_get_token(client, role="admin")
    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {platform_admin_token}"}
    ).json()
    assert any(u["email"] == member_email for u in users)


def test_cross_org_patient_panel_assignment_is_rejected():
    slug_a, _e1, admin_a_token = _signup_org()
    slug_b, _e2, _admin_b_token = _signup_org()

    provider_a_email, provider_a_token = _register_in_org(slug_a)
    patient_b_email, _ = _register_in_org(slug_b)

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_a_token}"}).json()
    # provider_a is visible to admin_a (same org); patient_b is NOT.
    provider_a_id = next(u["id"] for u in users if u["email"] == provider_a_email)

    platform_admin_token = register_and_get_token(client, role="admin")
    client.patch(
        f"/admin/users/{provider_a_id}/role",
        json={"role": "provider"},
        headers={"Authorization": f"Bearer {platform_admin_token}"},
    )
    all_users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {platform_admin_token}"}
    ).json()
    patient_b_id = next(u["id"] for u in all_users if u["email"] == patient_b_email)

    r = client.post(
        "/panel/assignments",
        json={"provider_id": provider_a_id, "patient_id": patient_b_id},
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    # admin_a can't even see patient_b (different org) — hidden as 404,
    # not the underlying 422 "different orgs" error.
    assert r.status_code == 404
    assert provider_a_token  # sanity: token was actually issued
