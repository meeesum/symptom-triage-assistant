"""Safety-critical test suite for the red-flag escalation engine.

These tests are the closest thing this project has to a clinical safety
sign-off at this stage. Every scenario here should map to a real-world
"if we get this wrong, someone could be harmed" case. When new rules are
added to rules.yaml, a corresponding test MUST be added here before the
rule is considered done — untested rules are not trusted rules.
"""

import pytest

from app.safety.engine import RedFlagEngine
from app.safety.schemas import (
    EscalationTier,
    OnsetSpeed,
    PatientContext,
    Severity,
    SymptomInput,
)


@pytest.fixture(scope="module")
def engine():
    return RedFlagEngine()


class TestEmergencyEscalations:
    def test_chest_pain_with_shortness_of_breath_is_emergency(self, engine):
        result = engine.evaluate(
            SymptomInput(symptom_ids=["chest_pain", "shortness_of_breath"])
        )
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "cardiac_event_pattern"

    def test_chest_pain_with_sweating_is_emergency(self, engine):
        result = engine.evaluate(
            SymptomInput(symptom_ids=["chest_pain", "sweating"])
        )
        assert result.tier == EscalationTier.EMERGENCY

    def test_stroke_fast_indicators_are_emergency(self, engine):
        for symptom in [
            "facial_drooping",
            "arm_weakness_one_sided",
            "slurred_speech",
            "sudden_confusion",
            "sudden_vision_loss",
        ]:
            result = engine.evaluate(SymptomInput(symptom_ids=[symptom]))
            assert result.tier == EscalationTier.EMERGENCY, f"{symptom} should escalate to emergency"
            assert result.matched_rule_id == "stroke_fast_pattern"

    def test_anaphylaxis_signs_are_emergency(self, engine):
        result = engine.evaluate(SymptomInput(symptom_ids=["throat_swelling"]))
        assert result.tier == EscalationTier.EMERGENCY
        assert "epinephrine" in result.guidance.lower()

    def test_suicidal_ideation_is_always_emergency_with_human_review(self, engine):
        result = engine.evaluate(SymptomInput(symptom_ids=["suicidal_thoughts"]))
        assert result.tier == EscalationTier.EMERGENCY
        assert result.requires_human_review is True
        assert "988" in result.guidance

    def test_pregnancy_with_severe_bleeding_is_emergency(self, engine):
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["heavy_vaginal_bleeding"],
                context=PatientContext(is_pregnant=True),
            )
        )
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "pregnancy_severe_bleeding_or_pain"

    def test_severe_bleeding_without_pregnancy_flag_does_not_use_pregnancy_rule(self, engine):
        # Same symptom, no pregnancy context -> should NOT match the
        # pregnancy-specific rule (guards against a context field being
        # silently ignored and over- or under-triggering).
        result = engine.evaluate(SymptomInput(symptom_ids=["heavy_vaginal_bleeding"]))
        assert result.matched_rule_id != "pregnancy_severe_bleeding_or_pain"

    def test_infant_fever_is_always_emergency_regardless_of_severity(self, engine):
        # This is the critical "always escalate regardless of appearance" case.
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["fever"],
                severity=Severity.MILD,  # deliberately mild — must still escalate
                context=PatientContext(age_years=0.1),
            )
        )
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "infant_high_fever"

    def test_fever_in_older_child_does_not_trigger_infant_rule(self, engine):
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["fever"],
                severity=Severity.SEVERE,
                context=PatientContext(age_years=5),
            )
        )
        assert result.matched_rule_id != "infant_high_fever"
        assert result.tier == EscalationTier.URGENT  # falls through to adult/general high-fever rule

    def test_head_injury_with_loss_of_consciousness_is_emergency(self, engine):
        result = engine.evaluate(
            SymptomInput(symptom_ids=["head_injury", "loss_of_consciousness"])
        )
        assert result.tier == EscalationTier.EMERGENCY

    def test_head_injury_alone_is_not_auto_emergency(self, engine):
        # A bare head injury with no other markers should not match the
        # all_of rule (which requires a second signal) — verifies all_of
        # actually requires ALL listed symptoms, not just one.
        result = engine.evaluate(SymptomInput(symptom_ids=["head_injury"]))
        assert result.matched_rule_id != "severe_head_injury"

    def test_loss_of_consciousness_alone_is_emergency(self, engine):
        # Added after adversarial eval case combo_01 (Phase 3) showed
        # fainting only escalated when paired with a head injury, missing
        # cardiac/neurological/other causes of unexplained fainting.
        result = engine.evaluate(SymptomInput(symptom_ids=["loss_of_consciousness"]))
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "unexplained_loss_of_consciousness"

    def test_severe_headache_is_emergency_regardless_of_onset(self, engine):
        # Added after a code review found that a bare "headache" symptom
        # fell through to the self-care fallback for ANY severity, since
        # default_mild_acute only gates on severity_at_least: mild (a
        # floor, not a ceiling) — "worst headache of my life" was being
        # triaged as self-care.
        result = engine.evaluate(
            SymptomInput(symptom_ids=["headache"], severity=Severity.SEVERE)
        )
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "severe_headache_red_flag"

    def test_severe_headache_emergency_does_not_require_sudden_onset(self, engine):
        # The bug specifically affected headaches with no explicit onset
        # marker (the LLM/keyword extractor wouldn't always catch
        # "suddenly") — the rule must not require onset=sudden to fire.
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["headache"], severity=Severity.SEVERE, onset=OnsetSpeed.UNKNOWN
            )
        )
        assert result.tier == EscalationTier.EMERGENCY
        assert result.matched_rule_id == "severe_headache_red_flag"


class TestUrgentEscalations:
    def test_isolated_chest_pain_without_combo_is_urgent_not_emergency(self, engine):
        result = engine.evaluate(SymptomInput(symptom_ids=["chest_pain"]))
        assert result.tier == EscalationTier.URGENT
        assert result.matched_rule_id == "chest_pain_isolated"

    def test_severe_fever_adult_is_urgent(self, engine):
        result = engine.evaluate(
            SymptomInput(symptom_ids=["fever"], severity=Severity.SEVERE)
        )
        assert result.tier == EscalationTier.URGENT

    def test_immunocompromised_with_fever_is_urgent_even_if_mild(self, engine):
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["fever"],
                severity=Severity.MILD,
                context=PatientContext(is_immunocompromised=True),
            )
        )
        # Immunocompromised rule doesn't gate on severity -> should still catch this
        assert result.tier == EscalationTier.URGENT
        assert result.matched_rule_id == "immunocompromised_infection_signs"


class TestRoutineAndSelfCare:
    def test_gradual_headache_is_routine(self, engine):
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["headache"],
                onset=OnsetSpeed.GRADUAL,
            )
        )
        assert result.tier == EscalationTier.ROUTINE

    def test_mild_acute_cough_is_self_care(self, engine):
        result = engine.evaluate(
            SymptomInput(
                symptom_ids=["cough"],
                severity=Severity.MILD,
                onset=OnsetSpeed.SUDDEN,
            )
        )
        assert result.tier == EscalationTier.SELF_CARE

    def test_unclassified_symptom_never_defaults_to_self_care(self, engine):
        # Fail-safe check: something the rule set has never heard of must
        # NOT silently resolve to "stay home", since that's the highest-risk
        # default. It should fall back to at least routine guidance.
        result = engine.evaluate(SymptomInput(symptom_ids=["some_unmapped_symptom_xyz"]))
        assert result.tier != EscalationTier.SELF_CARE
        assert result.matched_rule_id is None


class TestRuleOrderingAndPrecedence:
    def test_emergency_combo_beats_urgent_single_symptom_rule(self, engine):
        # chest_pain alone matches "chest_pain_isolated" (urgent), but with
        # shortness_of_breath it must match the emergency combo rule first.
        result = engine.evaluate(
            SymptomInput(symptom_ids=["chest_pain", "shortness_of_breath"])
        )
        assert result.tier == EscalationTier.EMERGENCY

    def test_no_symptoms_does_not_crash_and_is_not_self_care(self, engine):
        result = engine.evaluate(SymptomInput(symptom_ids=[]))
        assert result.tier != EscalationTier.SELF_CARE


class TestSeverityUnknownHandling:
    def test_unknown_severity_does_not_satisfy_severity_gated_rule(self, engine):
        # fever with unknown severity should NOT match "high_fever_adult"
        # (which requires severity_at_least: severe) — absence of info must
        # not be treated as meeting a minimum-severity threshold.
        result = engine.evaluate(SymptomInput(symptom_ids=["fever"]))
        assert result.matched_rule_id != "high_fever_adult"
