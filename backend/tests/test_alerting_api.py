"""API-level tests: verifies an emergency-tier triage actually triggers
a high-risk alert end-to-end through the real /triage endpoints, and that
GET /alerts/recent respects the same panel-based visibility as
GET /audit/recent. See app/api/alerts.py, app/api/triage.py, and
docs/phase7e-high-risk-alerting.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def test_emergency_triage_creates_an_alert():
    admin_token = register_and_get_token(client, role="admin")
    before = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()

    r = client.post(
        "/triage/evaluate", json={"symptom_ids": ["chest_pain", "shortness_of_breath"]}
    )
    assert r.status_code == 200
    assert r.json()["tier"] == "emergency"

    after = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert len(after) == len(before) + 1
    assert after[0]["status"] == "sent"


def test_non_emergency_triage_does_not_create_an_alert():
    admin_token = register_and_get_token(client, role="admin")
    before = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()

    r = client.post("/triage/evaluate", json={"symptom_ids": ["cough"], "severity": "mild"})
    assert r.status_code == 200
    assert r.json()["tier"] != "emergency"

    after = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert len(after) == len(before)


def test_urgent_triage_does_not_create_an_alert():
    # Only emergency tier pages — urgent is the fast path too, but not
    # high-risk enough for an on-call alert (see app/api/triage.py).
    admin_token = register_and_get_token(client, role="admin")
    before = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()

    r = client.post("/triage/evaluate", json={"symptom_ids": ["chest_pain"]})
    assert r.status_code == 200
    assert r.json()["tier"] == "urgent"

    after = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert len(after) == len(before)


def test_patient_cannot_view_alerts():
    token = register_and_get_token(client, role="patient")
    r = client.get("/alerts/recent", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_alert_recipient_matches_panel_assignment():
    admin_token = register_and_get_token(client, role="admin")
    provider_email, _ = register_new_patient(client)
    provider_token = promote(client, provider_email, "provider")
    patient_email, patient_token = register_new_patient(client)

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)
    client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200
    assert r.json()["tier"] == "emergency"

    alerts = client.get(
        "/alerts/recent?limit=1", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()
    assert len(alerts) == 1
    assert alerts[0]["recipient_provider_id"] == provider_id


def test_provider_alerts_scoped_to_panel():
    _outsider_email, outsider_token = register_new_patient(client)
    outsider_token = promote(client, _outsider_email, "provider")

    before = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {outsider_token}"}
    ).json()

    patient_email, patient_token = register_new_patient(client)
    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200

    after = client.get(
        "/alerts/recent?limit=200", headers={"Authorization": f"Bearer {outsider_token}"}
    ).json()
    # Not on this outsider provider's panel — the new alert must not show up.
    assert len(after) == len(before)
