"""API-level tests for consent + data rights. See app/api/consent.py,
app/api/data_rights.py, and docs/phase8b-consent-and-data-rights.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token, register_new_patient

client = TestClient(app)


def test_consent_requires_auth():
    r = client.post("/consent", json={"consent_type": "data_processing", "granted": True})
    assert r.status_code == 401


def test_submit_and_read_back_consent():
    token = register_and_get_token(client, role="patient")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/consent", json={"consent_type": "data_processing", "granted": True}, headers=headers
    )
    assert r.status_code == 201
    assert r.json()["granted"] is True

    history_r = client.get("/consent", headers=headers)
    assert history_r.status_code == 200
    assert len(history_r.json()) == 1


def test_invalid_consent_type_returns_422():
    token = register_and_get_token(client, role="patient")
    r = client.post(
        "/consent",
        json={"consent_type": "not_a_real_type", "granted": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_a_users_consent_history_is_private_to_them():
    token_a = register_and_get_token(client, role="patient")
    token_b = register_and_get_token(client, role="patient")
    client.post(
        "/consent",
        json={"consent_type": "data_processing", "granted": True},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    r = client.get("/consent", headers={"Authorization": f"Bearer {token_b}"})
    assert r.json() == []


def test_export_requires_auth():
    r = client.post("/data-rights/export")
    assert r.status_code == 401


def test_export_returns_own_data_including_chat_history():
    token = register_and_get_token(client, role="patient")
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/triage/intake", json={"text": "I have a mild cough"}, headers=headers
    )

    r = client.post("/data-rights/export", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["chat_history"]) == 1
    assert body["chat_history"][0]["user_text"] == "I have a mild cough"


def test_deletion_revokes_the_current_token_immediately():
    email, token = register_new_patient(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/data-rights/deletion", headers=headers)
    assert r.status_code == 200
    assert r.json()["request_type"] == "deletion"

    # The same token that just performed the deletion must now be dead.
    followup = client.get("/data-rights/requests", headers=headers)
    assert followup.status_code == 401


def test_deleted_account_cannot_log_in_again():
    email, token = register_new_patient(client)
    client.post("/data-rights/deletion", headers={"Authorization": f"Bearer {token}"})

    r = client.post(
        "/auth/login", json={"email": email, "password": "correct-horse-battery-staple"}
    )
    assert r.status_code == 401


def test_get_my_data_requests_lists_past_requests():
    token = register_and_get_token(client, role="patient")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/data-rights/export", headers=headers)

    r = client.get("/data-rights/requests", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["request_type"] == "export"
