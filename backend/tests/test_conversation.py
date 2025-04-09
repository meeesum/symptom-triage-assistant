from app.intake.conversation import build_symptom_from_turns, next_follow_up_question
from app.safety.schemas import OnsetSpeed, Severity


def test_build_symptom_from_single_turn_matches_extractor():
    symptom = build_symptom_from_turns(["I have a mild cough"])
    assert symptom.symptom_ids == ["cough"]
    assert symptom.severity == Severity.MILD


def test_build_symptom_from_turns_requires_at_least_one_turn():
    import pytest

    with pytest.raises(ValueError):
        build_symptom_from_turns([])


def test_build_symptom_merges_symptom_ids_across_turns():
    symptom = build_symptom_from_turns(["I have a cough", "also a sore throat"])
    assert set(symptom.symptom_ids) == {"cough", "sore_throat"}


def test_build_symptom_later_turn_fills_in_missing_severity():
    symptom = build_symptom_from_turns(["I have a cough", "it's pretty severe"])
    assert symptom.severity == Severity.SEVERE


def test_build_symptom_later_turn_fills_in_missing_onset():
    symptom = build_symptom_from_turns(["I have a cough", "it started suddenly"])
    assert symptom.onset == OnsetSpeed.SUDDEN


def test_build_symptom_first_turn_severity_not_overwritten_by_unknown_later_turn():
    symptom = build_symptom_from_turns(["severe cough", "also feeling tired"])
    assert symptom.severity == Severity.SEVERE


def test_build_symptom_free_text_accumulates_across_turns():
    symptom = build_symptom_from_turns(["I have a cough", "it started suddenly"])
    assert "cough" in symptom.free_text
    assert "suddenly" in symptom.free_text


def test_build_symptom_negation_scoped_to_its_own_turn():
    # "no chest pain" in turn 1 should not suppress a later turn's real
    # mention of a different symptom, and shouldn't leak negation scope
    # across turns the way concatenating raw text first could.
    symptom = build_symptom_from_turns(["no chest pain, just tired", "now I have a cough"])
    assert "chest_pain" not in symptom.symptom_ids
    assert "cough" in symptom.symptom_ids


def test_next_follow_up_question_asks_for_symptom_when_none_recognized():
    from app.safety.schemas import SymptomInput

    question = next_follow_up_question(SymptomInput(), turns_so_far=1)
    assert question is not None
    assert "symptom" in question.lower() or "describe" in question.lower()


def test_next_follow_up_question_asks_for_severity_when_missing():
    symptom = build_symptom_from_turns(["I have a cough"])
    question = next_follow_up_question(symptom, turns_so_far=1)
    assert question is not None
    assert "severe" in question.lower()


def test_next_follow_up_question_asks_for_onset_when_severity_known():
    symptom = build_symptom_from_turns(["I have a severe cough"])
    question = next_follow_up_question(symptom, turns_so_far=1)
    assert question is not None
    assert "start" in question.lower()


def test_next_follow_up_question_none_when_fully_confident():
    symptom = build_symptom_from_turns(["I have a severe cough that started suddenly"])
    assert next_follow_up_question(symptom, turns_so_far=1) is None


def test_next_follow_up_question_stops_after_max_follow_ups():
    from app.safety.schemas import SymptomInput

    # Still no symptom recognized even after the max number of follow-ups
    # — must finalize rather than ask forever.
    question = next_follow_up_question(SymptomInput(), turns_so_far=4)
    assert question is None
