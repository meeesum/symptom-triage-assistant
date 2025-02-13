"""Service-layer tests for the internationalization epic's safety-critical
half: the deterministic intake extractor recognizing symptoms in a
non-English language, not just the UI shell around it.

`test_every_rule_symptom_id_has_spanish_phrases` is the Spanish analogue of
test_intake_extractor.py's `test_every_rule_symptom_id_has_phrases` — same
reasoning: a symptom_id referenced by rules.yaml with no Spanish phrases
means a Spanish-speaking patient describing that exact symptom would never
trigger the rule, silently.
"""

import yaml

from app.intake.conversation import build_symptom_from_turns, next_follow_up_question
from app.intake.extractor import extract_symptom_input
from app.intake.symptom_phrases import PHRASES_BY_LANGUAGE, SUPPORTED_LANGUAGES
from app.safety.engine import _DEFAULT_RULES_PATH
from app.safety.schemas import OnsetSpeed, Severity


def _all_rule_symptom_ids() -> set[str]:
    with open(_DEFAULT_RULES_PATH) as f:
        raw = yaml.safe_load(f)
    ids = set()
    for rule in raw["rules"]:
        match = rule.get("match", {})
        ids.update(match.get("any_of", []))
        ids.update(match.get("all_of", []))
    return ids


def test_every_rule_symptom_id_has_spanish_phrases():
    missing = _all_rule_symptom_ids() - set(PHRASES_BY_LANGUAGE["es"]["symptom"].keys())
    assert not missing, f"symptom_ids used in rules.yaml with no Spanish phrases: {missing}"


def test_supported_languages_is_english_and_spanish():
    assert set(SUPPORTED_LANGUAGES) == {"en", "es"}


class TestSpanishExtraction:
    def test_chest_pain_phrase_detected(self):
        result = extract_symptom_input(
            "tengo dolor en el pecho y estoy sudando mucho", language="es"
        )
        assert "chest_pain" in result.symptom_ids
        assert "sweating" in result.symptom_ids

    def test_stroke_phrases_detected(self):
        result = extract_symptom_input(
            "se me cae la cara y hablo arrastrado", language="es"
        )
        assert "facial_drooping" in result.symptom_ids
        assert "slurred_speech" in result.symptom_ids

    def test_suicidal_phrase_detected(self):
        result = extract_symptom_input(
            "he estado pensando en el suicidio últimamente", language="es"
        )
        assert "suicidal_thoughts" in result.symptom_ids

    def test_no_symptom_match_returns_empty_list(self):
        result = extract_symptom_input("solo estoy revisando cómo funciona esto", language="es")
        assert result.symptom_ids == []

    def test_severity_and_onset_detected(self):
        result = extract_symptom_input(
            "tengo un dolor de cabeza severo que empezó de repente", language="es"
        )
        assert result.severity == Severity.SEVERE
        assert result.onset == OnsetSpeed.SUDDEN

    def test_negated_symptom_is_not_matched(self):
        # Spanish negation: "no" directly precedes the verb, same
        # window/clause-boundary heuristic as English — see extractor.py.
        result = extract_symptom_input(
            "no tengo dolor en el pecho, solo estoy muy cansado", language="es"
        )
        assert "chest_pain" not in result.symptom_ids
        assert "mild_fatigue" in result.symptom_ids

    def test_context_pregnancy_detected(self):
        result = extract_symptom_input("estoy embarazada y tengo náuseas", language="es")
        assert result.context.is_pregnant is True
        assert "nausea" in result.symptom_ids


class TestUnsupportedLanguageFallsBackToEnglish:
    def test_unknown_language_code_falls_back_to_english_phrases(self):
        # "fr" has no entry in PHRASES_BY_LANGUAGE — extract_symptom_input
        # falls back to English rather than raising, matching this
        # project's "never crash on unexpected input" API-boundary stance.
        result = extract_symptom_input("I have chest pain", language="fr")
        assert "chest_pain" in result.symptom_ids


class TestSpanishConversationFlow:
    def test_build_symptom_from_turns_in_spanish(self):
        symptom = build_symptom_from_turns(
            ["tengo dolor en el pecho", "es severo y empezó de repente"], language="es"
        )
        assert "chest_pain" in symptom.symptom_ids
        assert symptom.severity == Severity.SEVERE
        assert symptom.onset == OnsetSpeed.SUDDEN

    def test_follow_up_question_asked_in_spanish(self):
        symptom = extract_symptom_input("me duele algo", language="es")
        question = next_follow_up_question(symptom, turns_so_far=1, language="es")
        assert question is not None
        # Spot-check it's actually Spanish text, not the English default.
        assert "síntoma" in question or "detalle" in question

    def test_follow_up_question_defaults_to_english(self):
        symptom = extract_symptom_input("something hurts")
        question = next_follow_up_question(symptom, turns_so_far=1)
        assert question is not None
        assert "symptom" in question.lower()
