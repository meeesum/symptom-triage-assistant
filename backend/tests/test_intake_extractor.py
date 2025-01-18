"""Tests for the deterministic text -> SymptomInput extractor.

The most important test in this file is
`test_every_rule_symptom_id_has_phrases`: if a symptom_id is referenced by
rules.yaml but has no entry in symptom_phrases.py, a patient describing
that exact symptom in free text would silently never trigger the rule.
That's a safety gap, not a coverage nitpick.
"""

import yaml

from app.intake.extractor import extract_symptom_input
from app.intake.symptom_phrases import SYMPTOM_PHRASES
from app.safety.engine import RedFlagEngine, _DEFAULT_RULES_PATH
from app.safety.schemas import EscalationTier, OnsetSpeed, Severity


def _all_rule_symptom_ids() -> set[str]:
    with open(_DEFAULT_RULES_PATH) as f:
        raw = yaml.safe_load(f)
    ids = set()
    for rule in raw["rules"]:
        match = rule.get("match", {})
        ids.update(match.get("any_of", []))
        ids.update(match.get("all_of", []))
    return ids


def test_every_rule_symptom_id_has_phrases():
    missing = _all_rule_symptom_ids() - set(SYMPTOM_PHRASES.keys())
    assert not missing, f"symptom_ids used in rules.yaml with no extractable phrases: {missing}"


class TestSymptomMatching:
    def test_chest_pain_phrase_detected(self):
        result = extract_symptom_input("I have chest pain and I'm sweating a lot")
        assert "chest_pain" in result.symptom_ids
        assert "sweating" in result.symptom_ids

    def test_stroke_phrases_detected(self):
        result = extract_symptom_input("my face is drooping and my speech is slurred")
        assert "facial_drooping" in result.symptom_ids
        assert "slurred_speech" in result.symptom_ids

    def test_no_symptom_match_returns_empty_list(self):
        result = extract_symptom_input("just checking how this works")
        assert result.symptom_ids == []

    def test_suicidal_phrase_detected(self):
        result = extract_symptom_input("I've been thinking about suicide lately")
        assert "suicidal_thoughts" in result.symptom_ids


class TestNegationHandling:
    """Added after Phase 3 adversarial eval cases negation_01/negation_02
    surfaced that naive substring matching ignores negation entirely."""

    def test_negated_symptom_is_not_matched(self):
        result = extract_symptom_input("no chest pain, just really tired lately")
        assert "chest_pain" not in result.symptom_ids
        assert "mild_fatigue" in result.symptom_ids

    def test_negated_symptom_with_filler_words_is_not_matched(self):
        result = extract_symptom_input(
            "I don't have any shortness of breath, my main issue is a sore throat"
        )
        assert "shortness_of_breath" not in result.symptom_ids
        assert "sore_throat" in result.symptom_ids

    def test_negation_does_not_suppress_a_different_later_symptom(self):
        result = extract_symptom_input("I don't have a fever, but I do have chest pain")
        assert "fever" not in result.symptom_ids
        assert "chest_pain" in result.symptom_ids

    def test_negation_does_not_cross_a_sentence_boundary(self):
        result = extract_symptom_input(
            "I had no history of asthma. My chest pain started an hour ago."
        )
        assert "chest_pain" in result.symptom_ids

    def test_negated_first_mention_does_not_block_a_later_affirmed_mention(self):
        # Code-review bug: _match_symptom_ids used text.find() which only
        # checks the FIRST occurrence of a phrase. A negated mention early
        # in the message was blocking a later, affirmed mention of the
        # exact same phrase from ever being detected — missing a genuine
        # cardiac emergency.
        result = extract_symptom_input(
            "No chest pain earlier today, but now I have severe chest pain and sweating"
        )
        assert "chest_pain" in result.symptom_ids

    def test_negation_cue_followed_immediately_by_comma_is_still_detected(self):
        # Code-review bug: the cue "no " (with a literal trailing space)
        # never matched "No, chest pain." because a comma, not a space,
        # follows "No" — so the denial was silently ignored.
        result = extract_symptom_input("No, chest pain.")
        assert "chest_pain" not in result.symptom_ids


class TestSeverityAndOnset:
    def test_severe_detected(self):
        result = extract_symptom_input("I have severe abdominal pain")
        assert result.severity == Severity.SEVERE

    def test_worse_case_wins_when_multiple_severities_mentioned(self):
        result = extract_symptom_input("it started mild but now it's severe")
        assert result.severity == Severity.SEVERE

    def test_sudden_onset_detected(self):
        result = extract_symptom_input("my chest pain started suddenly")
        assert result.onset == OnsetSpeed.SUDDEN

    def test_unmentioned_severity_is_unknown(self):
        result = extract_symptom_input("I have a cough")
        assert result.severity == Severity.UNKNOWN


class TestContextExtraction:
    def test_pregnancy_detected(self):
        result = extract_symptom_input("I'm pregnant and have severe abdominal pain")
        assert result.context.is_pregnant is True

    def test_immunocompromised_detected(self):
        result = extract_symptom_input("I'm on chemo and have a fever")
        assert result.context.is_immunocompromised is True

    def test_negated_pregnancy_is_not_detected(self):
        # Found by the expanded adversarial eval suite: unlike symptom_ids,
        # context flags used to be matched with plain substring checks and
        # NO negation awareness at all — "I'm not pregnant" incorrectly
        # set is_pregnant=True, which could wrongly trigger
        # pregnancy_severe_bleeding_or_pain (over-triage — safe direction,
        # but a real correctness/trust bug: a clearly-not-pregnant patient
        # being told to seek care "for this combination during pregnancy"
        # undermines trust in every OTHER guidance the system gives). Fixed
        # by routing context matching through the same _is_negated() logic
        # symptom_ids already used — see _any_phrase_affirmed() in
        # extractor.py. See docs/phase10b-expanded-eval-and-load-testing.md.
        result = extract_symptom_input("I'm not pregnant, just have a headache")
        assert result.context.is_pregnant is False

    def test_negated_respiratory_history_is_not_detected(self):
        result = extract_symptom_input("no history of asthma, currently just have a runny nose")
        assert result.context.has_respiratory_history is False

    def test_age_in_months_converted_to_fractional_years(self):
        result = extract_symptom_input("my 3 month old has a fever")
        assert result.context.age_years == 0.25

    def test_age_in_years_parsed(self):
        result = extract_symptom_input("my 5 year old has a rash")
        assert result.context.age_years == 5.0

    def test_age_in_weeks_converted_to_fractional_years(self):
        # Found by the expanded adversarial eval suite: a young infant's
        # age is very commonly stated in weeks ("10 weeks old"), and
        # without this the infant_high_fever emergency rule's
        # age_years_max gate silently never fired for a real newborn —
        # exactly the population it exists to protect. See
        # docs/phase10b-expanded-eval-and-load-testing.md.
        result = extract_symptom_input("my baby is 10 weeks old and has a fever")
        assert result.context.age_years == round(10 / 52, 3)

    def test_infant_fever_in_weeks_escalates_to_emergency(self):
        from app.safety.engine import RedFlagEngine

        result = extract_symptom_input("my newborn, 6 weeks old, feels warm")
        escalation = RedFlagEngine().evaluate(result)
        assert escalation.tier.value == "emergency"
        assert escalation.matched_rule_id == "infant_high_fever"

    def test_no_age_mentioned_is_none(self):
        result = extract_symptom_input("I have a headache")
        assert result.context.age_years is None


class TestEndToEndAgainstSafetyEngine:
    """The extractor is only as good as what it hands to the rule engine —
    these tests run realistic patient sentences all the way through."""

    def test_cardiac_sentence_escalates_to_emergency(self):
        engine = RedFlagEngine()
        symptom = extract_symptom_input(
            "I suddenly have really bad chest pain and I'm sweating and feel nauseous"
        )
        result = engine.evaluate(symptom)
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "cardiac_event_pattern"

    def test_infant_fever_sentence_escalates_to_emergency(self):
        engine = RedFlagEngine()
        symptom = extract_symptom_input("my 2 month old baby has a fever")
        result = engine.evaluate(symptom)
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "infant_high_fever"

    def test_pregnancy_bleeding_sentence_escalates_to_emergency(self):
        engine = RedFlagEngine()
        symptom = extract_symptom_input("I'm pregnant and having heavy vaginal bleeding")
        result = engine.evaluate(symptom)
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "pregnancy_severe_bleeding_or_pain"

    def test_mild_cough_sentence_stays_self_care(self):
        engine = RedFlagEngine()
        symptom = extract_symptom_input("I have a mild cough that started suddenly")
        result = engine.evaluate(symptom)
        assert result.tier == EscalationTier.SELF_CARE
