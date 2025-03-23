"""Regression tests for the org_admin access gap found and fixed while
building the admin action audit log (docs/phase8c-admin-action-audit-log.md):
six Phase 03 endpoints previously gated on require_role("provider",
"admin") only, giving org_admin a flat 403 despite being described as a
per-org superset of provider. These tests prove org_admin can now use
each endpoint AND stays correctly scoped to their own org.
"""

import itertools

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token

client = TestClient(app)

_slug_counter = itertools.count()


def _signup_org() -> tuple[str, str]:
    n = next(_slug_counter)
    slug = f"orgfix-{n}"
    admin_email = f"orgfixadmin-{n}@example.com"
    r = client.post(
        "/organizations",
        json={
            "name": f"OrgFix {n}",
            "slug": slug,
            "admin_email": admin_email,
            "admin_password": "correct-horse-battery-staple",
        },
    )
    assert r.status_code == 201, r.text
    token = client.post(
        "/auth/login", json={"email": admin_email, "password": "correct-horse-battery-staple"}
    ).json()["access_token"]
    return slug, token


def _register_patient_in_org(slug: str) -> tuple[str, str]:
    n = next(_slug_counter)
    email = f"orgfix-patient-{n}@example.com"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-battery-staple", "org_slug": slug},
    )
    assert r.status_code == 201, r.text
    return email, r.json()["access_token"]


def test_org_admin_can_view_audit_recent():
    slug, org_admin_token = _signup_org()
    r = client.get("/audit/recent", headers={"Authorization": f"Bearer {org_admin_token}"})
    assert r.status_code == 200


def test_org_admin_can_view_analytics():
    slug, org_admin_token = _signup_org()
    r = client.get("/audit/analytics", headers={"Authorization": f"Bearer {org_admin_token}"})
    assert r.status_code == 200


def test_org_admin_can_view_alerts():
    slug, org_admin_token = _signup_org()
    r = client.get("/alerts/recent", headers={"Authorization": f"Bearer {org_admin_token}"})
    assert r.status_code == 200


def test_org_admin_can_view_and_create_clinical_notes():
    slug, org_admin_token = _signup_org()
    _patient_email, patient_token = _register_patient_in_org(slug)
    client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    record_id = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {org_admin_token}"}
    ).json()[0]["id"]

    create_r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "org_admin note"},
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert create_r.status_code == 201, create_r.text

    get_r = client.get(
        f"/audit/{record_id}/notes", headers={"Authorization": f"Bearer {org_admin_token}"}
    )
    assert get_r.status_code == 200
    assert len(get_r.json()) == 1


def test_org_admin_can_manage_referrals():
    slug, org_admin_token = _signup_org()
    _patient_email, patient_token = _register_patient_in_org(slug)
    client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    record_id = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {org_admin_token}"}
    ).json()[0]["id"]

    create_r = client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {org_admin_token}"}
    )
    assert create_r.status_code == 201, create_r.text

    get_r = client.get(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {org_admin_token}"}
    )
    assert get_r.status_code == 200

    patch_r = client.patch(
        f"/audit/{record_id}/referral",
        json={"status": "seen"},
        headers={"Authorization": f"Bearer {org_admin_token}"},
    )
    assert patch_r.status_code == 200


def test_org_admin_can_view_their_own_panel():
    slug, org_admin_token = _signup_org()
    r = client.get("/panel/mine", headers={"Authorization": f"Bearer {org_admin_token}"})
    assert r.status_code == 200


def test_org_admin_cannot_view_another_orgs_audit_records():
    slug_a, org_admin_a_token = _signup_org()
    slug_b, org_admin_b_token = _signup_org()
    _patient_b_email, patient_b_token = _register_patient_in_org(slug_b)

    client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_b_token}"},
    )
    # The specific record id org_admin_b's own view produces — a
    # before/after or existence check by id, not a rule-name heuristic
    # that could false-positive on unrelated data from other tests
    # sharing this DB.
    record_id_b = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {org_admin_b_token}"}
    ).json()[0]["id"]

    log_a_ids = {
        r["id"]
        for r in client.get(
            "/audit/recent?limit=200", headers={"Authorization": f"Bearer {org_admin_a_token}"}
        ).json()
    }
    assert record_id_b not in log_a_ids


def test_org_admin_cannot_view_another_orgs_clinical_notes():
    slug_a, org_admin_a_token = _signup_org()
    slug_b, org_admin_b_token = _signup_org()
    _patient_b_email, patient_b_token = _register_patient_in_org(slug_b)

    client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_b_token}"},
    )
    record_id = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {org_admin_b_token}"}
    ).json()[0]["id"]

    r = client.get(
        f"/audit/{record_id}/notes", headers={"Authorization": f"Bearer {org_admin_a_token}"}
    )
    assert r.status_code == 404


def test_platform_admin_unaffected_by_org_admin_changes():
    platform_admin_token = register_and_get_token(client, role="admin")
    r = client.get("/audit/recent", headers={"Authorization": f"Bearer {platform_admin_token}"})
    assert r.status_code == 200
    r2 = client.get("/audit/analytics", headers={"Authorization": f"Bearer {platform_admin_token}"})
    assert r2.status_code == 200
