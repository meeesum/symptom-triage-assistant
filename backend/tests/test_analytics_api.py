"""API-level tests for GET /audit/analytics — see app/api/analytics.py
and docs/phase7d-provider-analytics.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def test_patient_cannot_view_analytics():
    token = register_and_get_token(client, role="patient")
    r = client.get("/audit/analytics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_view_analytics():
    token = register_and_get_token(client, role="admin")
    r = client.get("/audit/analytics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert "volume_by_day" in body
    assert "tier_distribution" in body
    assert "time_to_follow_up" in body
    assert body["window_days"] == 30


def test_analytics_days_param_is_clamped():
    token = register_and_get_token(client, role="admin")
    r = client.get("/audit/analytics?days=9999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["window_days"] == 365
    assert len(r.json()["volume_by_day"]) == 365


def test_analytics_reflects_provider_panel_scoping():
    admin_token = register_and_get_token(client, role="admin")
    provider_email, _ = register_new_patient(client)
    provider_token = promote(client, provider_email, "provider")
    patient_email, patient_token = register_new_patient(client)

    before = client.get(
        "/audit/analytics", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()["tier_distribution"]["emergency"]

    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200

    after_unassigned = client.get(
        "/audit/analytics", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()["tier_distribution"]["emergency"]
    # Not on the panel yet — shouldn't show up.
    assert after_unassigned == before

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)
    client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    after_assigned = client.get(
        "/audit/analytics", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()["tier_distribution"]["emergency"]
    assert after_assigned == before + 1
