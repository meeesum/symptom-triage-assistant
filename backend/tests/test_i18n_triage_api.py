"""API-layer tests: prove /triage/intake's `language` field actually
changes extraction and (where retrieval has Spanish coverage) the
returned explanation — not just that the backend accepts the field.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.safety.engine import _DEFAULT_RULES_PATH, load_rules
from app.safety.guidance_translations import GUIDANCE_ES

client = TestClient(app)


def test_every_rule_has_a_spanish_guidance_translation():
    # A rule with no Spanish entry silently falls back to English guidance
    # for Spanish patients — safe, but it should never be an ACCIDENTAL
    # gap for an existing rule. New rules added later need a matching
    # entry added here (or the fallback is a deliberate, temporary choice).
    rule_ids = {r.id for r in load_rules(_DEFAULT_RULES_PATH)}
    missing = rule_ids - set(GUIDANCE_ES.keys())
    assert not missing, f"rules.yaml rule ids with no Spanish guidance: {missing}"


def test_intake_understands_spanish_symptom_text():
    r = client.post(
        "/triage/intake",
        json={"text": "tengo un dolor de cabeza leve", "language": "es"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood_symptom_ids"] == ["headache"]
    assert body["understood_severity"] == "mild"


def test_intake_emergency_escalation_works_in_spanish():
    r = client.post(
        "/triage/intake",
        json={
            "text": "de repente tengo dolor en el pecho, es severo, y estoy sudando",
            "language": "es",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "emergency"
    assert "chest_pain" in body["understood_symptom_ids"]
    assert "sweating" in body["understood_symptom_ids"]
    # The emergency-tier guidance text itself must be in Spanish too — not
    # just symptom recognition. See app/safety/guidance_translations.py:
    # showing English "call 911 now" text to a Spanish-speaking patient at
    # the exact moment of an emergency would defeat the point of this epic.
    assert body["matched_rule_id"] == "cardiac_event_pattern"
    assert "servicios de emergencia" in body["guidance"].lower()


def test_intake_self_care_spanish_gets_spanish_grounded_explanation():
    r = client.post(
        "/triage/intake",
        json={"text": "tengo un poco de tos y dolor de garganta", "language": "es"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] in {"self_care", "routine"}
    # Extractive-fallback explanation quotes the Spanish KB article
    # verbatim (no ANTHROPIC_API_KEY configured in test/CI env) — proves
    # the Spanish retriever/KB path is actually wired into the API, not
    # just unit-tested in isolation.
    assert "resfriado" in body["guidance"].lower() or "tos" in body["guidance"].lower()


def test_evaluate_emergency_guidance_is_spanish_when_requested():
    # /triage/evaluate takes structured SymptomInput directly (no
    # extraction involved) — this isolates that _localize_guidance() in
    # app/api/triage.py is reached from the OTHER entry point too, not
    # just /triage/intake.
    r = client.post(
        "/triage/evaluate?language=es",
        json={"symptom_ids": ["chest_pain", "sweating"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "emergency"
    assert "infarto" in body["guidance"].lower() or "emergencia" in body["guidance"].lower()


def test_intake_defaults_to_english_when_language_omitted():
    r = client.post("/triage/intake", json={"text": "I have a mild cough"})
    assert r.status_code == 200
    assert r.json()["understood_symptom_ids"] == ["cough"]


def test_intake_unsupported_language_code_falls_back_to_english():
    r = client.post(
        "/triage/intake", json={"text": "I have chest pain", "language": "fr"}
    )
    assert r.status_code == 200
    assert "chest_pain" in r.json()["understood_symptom_ids"]


def test_intake_follow_up_question_is_in_spanish():
    r = client.post(
        "/triage/intake",
        json={"text": "no me siento bien", "language": "es", "allow_follow_up": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "need_more_info"
    assert "síntoma" in body["follow_up_question"] or "detalle" in body["follow_up_question"]
