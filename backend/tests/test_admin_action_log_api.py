"""API-level tests: proves each sensitive action actually gets logged
through the real endpoints, not just that the service function works in
isolation. See app/services/admin_action_log.py and
docs/phase8c-admin-action-audit-log.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def test_action_log_requires_auth():
    r = client.get("/admin/action-log")
    assert r.status_code == 401


def test_patient_cannot_view_action_log():
    token = register_and_get_token(client, role="patient")
    r = client.get("/admin/action-log", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_role_change_is_logged():
    admin_token = register_and_get_token(client, role="admin")
    email, _ = register_new_patient(client)
    promote(client, email, "provider")

    r = client.get("/admin/action-log?limit=200", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    role_changes = [a for a in r.json() if a["action"] == "role_change"]
    assert any(a["detail"]["to_role"] == "provider" for a in role_changes)


def test_panel_assignment_and_unassignment_are_logged():
    admin_token = register_and_get_token(client, role="admin")
    provider_email, _ = register_new_patient(client)
    promote(client, provider_email, "provider")
    patient_email, _ = register_new_patient(client)

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)

    create_r = client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assignment_id = create_r.json()["id"]
    client.delete(
        f"/panel/assignments/{assignment_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )

    log = client.get(
        "/admin/action-log?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assign_entries = [a for a in log if a["action"] == "panel_assign"]
    unassign_entries = [a for a in log if a["action"] == "panel_unassign"]
    assert any(a["target_id"] == str(assignment_id) for a in assign_entries)
    assert any(a["target_id"] == str(assignment_id) for a in unassign_entries)


def test_org_creation_is_logged():
    r = client.post(
        "/organizations",
        json={
            "name": "Logged Org",
            "slug": "logged-org-test",
            "admin_email": "admin@logged-org-test.example",
            "admin_password": "correct-horse-battery-staple",
        },
    )
    assert r.status_code == 201
    org_id = r.json()["id"]

    admin_login = client.post(
        "/auth/login",
        json={"email": "admin@logged-org-test.example", "password": "correct-horse-battery-staple"},
    )
    org_admin_token = admin_login.json()["access_token"]

    log = client.get(
        "/admin/action-log?limit=200", headers={"Authorization": f"Bearer {org_admin_token}"}
    ).json()
    assert any(a["action"] == "org_created" and a["target_id"] == str(org_id) for a in log)


def test_kb_review_approve_and_reject_are_logged():
    admin_token = register_and_get_token(client, role="admin")
    submitter_token = register_and_get_token(client, role="provider")
    reviewer_token = register_and_get_token(client, role="provider")

    def _submit(article_id: str) -> int:
        r = client.post(
            "/kb-review/submissions",
            json={
                "article_id": article_id,
                "title": "Test Article",
                "tags": ["test"],
                "source_note": "PLACEHOLDER",
                "body": ["Some body text."],
            },
            headers={"Authorization": f"Bearer {submitter_token}"},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    approve_id = _submit("test_article_approve_log")
    reject_id = _submit("test_article_reject_log")

    client.post(
        f"/kb-review/submissions/{approve_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    client.post(
        f"/kb-review/submissions/{reject_id}/reject",
        json={"review_note": "not good enough"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )

    log = client.get(
        "/admin/action-log?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert any(
        a["action"] == "kb_submission_approved" and a["target_id"] == str(approve_id) for a in log
    )
    assert any(
        a["action"] == "kb_submission_rejected" and a["target_id"] == str(reject_id) for a in log
    )


def test_viewing_clinical_notes_and_referral_is_logged():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200
    record_id = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()[0]["id"]

    client.get(f"/audit/{record_id}/notes", headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"})
    client.get(f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"})

    log = client.get(
        "/admin/action-log?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert any(
        a["action"] == "viewed_clinical_notes" and a["target_id"] == str(record_id) for a in log
    )
    assert any(a["action"] == "viewed_referral" and a["target_id"] == str(record_id) for a in log)


def test_org_admin_action_log_scoped_to_their_own_org():
    slug_a = "action-log-org-a"
    slug_b = "action-log-org-b"
    for slug in (slug_a, slug_b):
        client.post(
            "/organizations",
            json={
                "name": slug,
                "slug": slug,
                "admin_email": f"admin@{slug}.example",
                "admin_password": "correct-horse-battery-staple",
            },
        )

    admin_a_token = client.post(
        "/auth/login",
        json={"email": f"admin@{slug_a}.example", "password": "correct-horse-battery-staple"},
    ).json()["access_token"]
    admin_b_token = client.post(
        "/auth/login",
        json={"email": f"admin@{slug_b}.example", "password": "correct-horse-battery-staple"},
    ).json()["access_token"]

    # admin_b takes an action (role change on themselves-adjacent user via
    # a fresh registration in org b) — org_admin can't grant admin, so
    # promote to provider instead.
    r = client.post(
        "/auth/register",
        json={
            "email": "member-scoped-log@example.com",
            "password": "correct-horse-battery-staple",
            "org_slug": slug_b,
        },
    )
    assert r.status_code == 201
    users_b = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_b_token}"}
    ).json()
    member_id = next(u["id"] for u in users_b if u["email"] == "member-scoped-log@example.com")
    client.patch(
        f"/admin/users/{member_id}/role",
        json={"role": "provider"},
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )

    log_a = client.get(
        "/admin/action-log?limit=200", headers={"Authorization": f"Bearer {admin_a_token}"}
    ).json()
    assert not any(a["target_id"] == str(member_id) for a in log_a)
