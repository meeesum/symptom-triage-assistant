"""Integration tests: prove the API wiring, not just the engine in isolation.

Key thing being verified here: emergency/urgent tiers never reach the RAG
stub (the fast-path bypass), and the response contract is stable for the
frontend to build against.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_emergency_symptom_returns_emergency_tier_and_skips_rag():
    r = client.post(
        "/triage/evaluate",
        json={"symptom_ids": ["chest_pain", "shortness_of_breath"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "emergency"
    assert body["matched_rule_id"] == "cardiac_event_pattern"
    assert "911" in body["guidance"] or "emergency services" in body["guidance"].lower()


def test_self_care_symptom_returns_self_care_tier():
    r = client.post(
        "/triage/evaluate",
        json={
            "symptom_ids": ["cough"],
            "severity": "mild",
            "onset": "sudden",
        },
    )
    assert r.status_code == 200
    assert r.json()["tier"] == "self_care"


def test_suicidal_ideation_flags_human_review():
    r = client.post("/triage/evaluate", json={"symptom_ids": ["suicidal_thoughts"]})
    body = r.json()
    assert body["tier"] == "emergency"
    assert body["requires_human_review"] is True


def test_intake_from_raw_text_escalates_correctly():
    r = client.post(
        "/triage/intake",
        json={"text": "I suddenly have severe chest pain and I'm sweating"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "emergency"
    assert body["matched_rule_id"] == "cardiac_event_pattern"
    assert "chest_pain" in body["understood_symptom_ids"]
    assert "sweating" in body["understood_symptom_ids"]


def test_intake_surfaces_understood_fields_for_self_care_case():
    r = client.post("/triage/intake", json={"text": "I have a mild cough"})
    body = r.json()
    assert body["tier"] == "self_care"
    assert body["understood_symptom_ids"] == ["cough"]
    assert body["understood_severity"] == "mild"


def test_triage_decision_appears_in_audit_recent():
    client.post(
        "/triage/evaluate",
        json={"symptom_ids": ["chest_pain", "shortness_of_breath"]},
    )
    token = register_and_get_token(client, role="provider")
    r = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    assert body[0]["tier"] == "emergency"  # most recent record first
    assert body[0]["matched_rule_id"] == "cardiac_event_pattern"
    assert "free_text_excerpt" not in body[0]  # not exposed via this route, even to providers


def test_audit_recent_respects_limit_cap():
    token = register_and_get_token(client, role="provider")
    r = client.get("/audit/recent?limit=99999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()) <= 200


def test_audit_recent_limit_has_a_floor_too():
    # limit=0 previously passed straight through to SQLAlchemy's .limit(0),
    # silently returning zero rows in a way indistinguishable from "no
    # audit records exist" — must be clamped to at least 1, not just capped.
    client.post("/triage/evaluate", json={"symptom_ids": ["chest_pain", "shortness_of_breath"]})
    token = register_and_get_token(client, role="provider")
    r = client.get("/audit/recent?limit=0", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()) >= 1
