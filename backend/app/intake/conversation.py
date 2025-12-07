"""Multi-turn conversation state for /triage/intake.

The extractor (app/intake/extractor.py) already turns one message into a
SymptomInput; this module turns a SEQUENCE of messages into one merged
SymptomInput, and decides whether the merged result is confident enough
to triage or whether a targeted follow-up question would help first.

SAFETY-CRITICAL ordering, matching the rest of this codebase's fast-path
pattern: a follow-up question is only ever offered when the safety engine
has ALREADY evaluated the merged symptom and found it emergency/urgent —
tier is checked in app/api/triage.py BEFORE this module's
next_follow_up_question() is even called, and the fast path always wins.
A patient describing an emergency is never made to answer more questions
before getting emergency guidance, no matter how little else is known.

Opt-in, not automatic: IntakeRequest.allow_follow_up defaults to False, so
every existing caller of /triage/intake (including the structured
/triage/evaluate path, which never goes through this module at all) keeps
getting an immediate, single-shot triage decision exactly as before. Only
a caller that explicitly sets allow_follow_up=True (the new frontend
multi-turn UI) gets a follow-up question instead of a decision when
confidence is low.

Each turn is extracted independently, THEN merged — not concatenated into
one blob before extraction. Concatenating first would let the negation
heuristic's clause-boundary logic (see extractor.py's docstring) bleed
across what were really separate messages; extracting per-turn keeps each
message's own negation scoping intact.
"""

from __future__ import annotations

from app.intake.extractor import extract_symptom_input
from app.intake.symptom_phrases import DEFAULT_LANGUAGE
from app.safety.schemas import OnsetSpeed, PatientContext, Severity, SymptomInput

MAX_FOLLOW_UPS = 2  # after this many follow-up turns, finalize regardless of confidence

_FOLLOW_UP_TEXT = {
    "en": {
        "no_symptom": (
            "I wasn't able to identify a specific symptom from that — could "
            "you describe what you're experiencing in a bit more detail?"
        ),
        "severity": "How severe would you say this is — mild, moderate, or severe?",
        "onset": (
            "When did this start — suddenly, in the last day or two, or has "
            "it been building up gradually over weeks?"
        ),
    },
    "es": {
        "no_symptom": (
            "No pude identificar un síntoma específico en eso — ¿podrías "
            "describir con más detalle lo que estás sintiendo?"
        ),
        "severity": "¿Qué tan severo dirías que es esto — leve, moderado o severo?",
        "onset": (
            "¿Cuándo comenzó esto — de repente, en el último día o dos, o ha "
            "ido empeorando gradualmente durante semanas?"
        ),
    },
}


def _merge_context(base: PatientContext, new: PatientContext) -> PatientContext:
    return PatientContext(
        age_years=new.age_years if new.age_years is not None else base.age_years,
        is_pregnant=base.is_pregnant or new.is_pregnant,
        has_cardiac_history=base.has_cardiac_history or new.has_cardiac_history,
        has_respiratory_history=base.has_respiratory_history or new.has_respiratory_history,
        is_immunocompromised=base.is_immunocompromised or new.is_immunocompromised,
    )


def _merge(base: SymptomInput, new: SymptomInput) -> SymptomInput:
    merged_symptom_ids = list(dict.fromkeys([*base.symptom_ids, *new.symptom_ids]))
    return SymptomInput(
        symptom_ids=merged_symptom_ids,
        severity=new.severity if new.severity != Severity.UNKNOWN else base.severity,
        onset=new.onset if new.onset != OnsetSpeed.UNKNOWN else base.onset,
        duration_hours=(
            new.duration_hours if new.duration_hours is not None else base.duration_hours
        ),
        context=_merge_context(base.context, new.context),
        free_text=f"{base.free_text} {new.free_text}".strip(),
    )


def build_symptom_from_turns(turns: list[str], language: str = DEFAULT_LANGUAGE) -> SymptomInput:
    """Extract each turn independently and merge, oldest turn first."""
    if not turns:
        raise ValueError("build_symptom_from_turns requires at least one turn")

    merged = extract_symptom_input(turns[0], language=language)
    for text in turns[1:]:
        merged = _merge(merged, extract_symptom_input(text, language=language))
    return merged


def next_follow_up_question(
    symptom: SymptomInput, turns_so_far: int, language: str = DEFAULT_LANGUAGE
) -> str | None:
    """Returns a follow-up question, or None if confident enough to triage now.

    turns_so_far counts the current turn (1 for a first message with no
    prior_turns). Once turns_so_far exceeds MAX_FOLLOW_UPS + 1 (the
    original turn plus MAX_FOLLOW_UPS follow-up answers), always returns
    None — asking indefinitely would frustrate the patient more than
    triaging on incomplete information helps; the safety engine's
    guidance already accounts for uncertainty (see the unmatched-symptom
    fallback in app/safety/engine.py).

    The question itself is asked in the patient's chosen language
    (`_FOLLOW_UP_TEXT`) — a follow-up asked in the wrong language is
    functionally the same failure as no follow-up at all.
    """
    if turns_so_far > MAX_FOLLOW_UPS + 1:
        return None

    text = _FOLLOW_UP_TEXT.get(language, _FOLLOW_UP_TEXT[DEFAULT_LANGUAGE])

    if not symptom.symptom_ids:
        return text["no_symptom"]
    if symptom.severity == Severity.UNKNOWN:
        return text["severity"]
    if symptom.onset == OnsetSpeed.UNKNOWN:
        return text["onset"]
    return None
