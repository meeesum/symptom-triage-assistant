"""API-level tests for multi-turn /triage/intake — see
app/intake/conversation.py and docs/phase6c-multi-turn-triage.md.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_intake_without_allow_follow_up_finalizes_immediately_even_if_incomplete():
    # Default (allow_follow_up omitted) must behave exactly like before
    # this epic — no follow-up question, ever, regardless of confidence.
    r = client.post("/triage/intake", json={"text": "I have a mild cough"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert "tier" in body
    assert "follow_up_question" not in body


def test_intake_with_allow_follow_up_asks_when_severity_missing():
    r = client.post(
        "/triage/intake",
        json={"text": "I have a cough", "allow_follow_up": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "need_more_info"
    assert "severe" in body["follow_up_question"].lower()
    assert body["understood_symptom_ids"] == ["cough"]


def test_intake_multi_turn_completes_once_prior_turns_fill_the_gaps():
    r = client.post(
        "/triage/intake",
        json={
            "text": "it's pretty mild and started a few days ago, building up gradually",
            "prior_turns": ["I have a cough"],
            "allow_follow_up": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["understood_symptom_ids"] == ["cough"]
    assert body["understood_severity"] == "mild"
    assert body["understood_onset"] == "gradual"


def test_intake_emergency_tier_never_asks_a_follow_up_even_with_allow_follow_up():
    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating", "allow_follow_up": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["tier"] == "emergency"


def test_intake_follow_up_turns_eventually_finalize_even_if_still_unclear():
    r = client.post(
        "/triage/intake",
        json={
            "text": "still not sure",
            "prior_turns": ["not sure what's wrong", "just feeling off", "hard to say"],
            "allow_follow_up": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Four total turns exceeds MAX_FOLLOW_UPS (2) + the original turn — must
    # finalize rather than ask indefinitely, even with nothing understood.
    assert body["status"] == "complete"


def test_intake_incomplete_turn_is_not_saved_to_chat_history():
    from tests._auth_helpers import register_and_get_token

    token = register_and_get_token(client, role="patient")
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/triage/intake",
        json={"text": "I have a cough", "allow_follow_up": True},
        headers=headers,
    )

    r = client.get("/triage/history", headers=headers)
    assert r.status_code == 200
    assert r.json() == []
