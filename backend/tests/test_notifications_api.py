"""API-level tests for self-service notification preferences and the
end-to-end alerting -> notification wiring. See app/api/notifications.py,
app/services/alerting.py, and docs/phase7f-notifications.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def test_get_preferences_defaults_without_ever_setting_them():
    token = register_and_get_token(client, role="provider")
    r = client.get("/notifications/preferences", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email_enabled"] is True
    assert body["sms_enabled"] is False
    assert body["phone_number"] is None


def test_put_preferences_then_get_reflects_the_update():
    token = register_and_get_token(client, role="provider")
    headers = {"Authorization": f"Bearer {token}"}

    put_r = client.put(
        "/notifications/preferences",
        json={"email_enabled": False, "sms_enabled": True, "phone_number": "+15551234567"},
        headers=headers,
    )
    assert put_r.status_code == 200
    assert put_r.json()["sms_enabled"] is True

    get_r = client.get("/notifications/preferences", headers=headers)
    assert get_r.json() == {
        "email_enabled": False,
        "sms_enabled": True,
        "phone_number": "+15551234567",
    }


def test_preferences_require_auth():
    r = client.get("/notifications/preferences")
    assert r.status_code == 401


def test_a_users_preferences_do_not_affect_another_users():
    token_a = register_and_get_token(client, role="provider")
    token_b = register_and_get_token(client, role="provider")

    client.put(
        "/notifications/preferences",
        json={"email_enabled": False, "sms_enabled": True, "phone_number": "+15550000000"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    r = client.get(
        "/notifications/preferences", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.json()["email_enabled"] is True
    assert r.json()["sms_enabled"] is False


def test_emergency_triage_dispatches_a_notification_to_the_panel_provider(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.alerting.notify_user",
        lambda user_id, subject, message: sent.append((user_id, subject, message)),
    )

    admin_token = register_and_get_token(client, role="admin")
    provider_email, _ = register_new_patient(client)
    promote(client, provider_email, "provider")
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

    assert len(sent) == 1
    assert sent[0][0] == provider_id
    assert sent[0][1] == "High-risk triage alert"


def test_emergency_triage_with_no_panel_provider_does_not_call_notify(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.alerting.notify_user",
        lambda *args, **kwargs: calls.append(args),
    )

    r = client.post(
        "/triage/evaluate", json={"symptom_ids": ["chest_pain", "shortness_of_breath"]}
    )
    assert r.status_code == 200
    assert r.json()["tier"] == "emergency"
    assert calls == []
