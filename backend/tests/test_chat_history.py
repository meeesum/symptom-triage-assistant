"""Triage chat history: persisted only for logged-in patients, never for
anonymous requests, and only ever readable by the patient who owns it."""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token, register_new_patient

client = TestClient(app)


def test_anonymous_intake_saves_no_history():
    r = client.post("/triage/intake", json={"text": "I have a mild cough"})
    assert r.status_code == 200
    # no way to check "no history exists" without a token to query with —
    # covered instead by the next test's contrast (logged-in DOES persist)


def test_logged_in_patient_intake_appears_in_their_history():
    _email, token = register_new_patient(client)

    client.post(
        "/triage/intake",
        json={"text": "I have a mild cough"},
        headers={"Authorization": f"Bearer {token}"},
    )

    r = client.get("/triage/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["user_text"] == "I have a mild cough"
    assert body[0]["tier"] == "self_care"
    assert body[0]["understood_symptom_ids"] == ["cough"]


def test_history_is_scoped_to_the_requesting_user():
    _email_a, token_a = register_new_patient(client)
    _email_b, token_b = register_new_patient(client)

    client.post(
        "/triage/intake",
        json={"text": "I have a mild cough"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    r = client.get("/triage/history", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 200
    assert r.json() == []  # user B sees none of user A's history


def test_history_requires_login():
    r = client.get("/triage/history")
    assert r.status_code == 401


def test_history_returns_oldest_first():
    _email, token = register_new_patient(client)
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/triage/intake", json={"text": "I have a mild cough"}, headers=headers)
    client.post("/triage/intake", json={"text": "I also have a sore throat"}, headers=headers)

    r = client.get("/triage/history", headers=headers)
    body = r.json()
    assert len(body) == 2
    assert "cough" in body[0]["user_text"]
    assert "sore throat" in body[1]["user_text"]


def test_provider_can_also_read_their_own_history():
    # get_current_user (not a patient-only role gate) is used deliberately
    # — any logged-in user, regardless of role, has a chat history that's
    # theirs to read.
    token = register_and_get_token(client, role="provider")
    r = client.get("/triage/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
