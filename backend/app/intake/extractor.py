"""Deterministic free-text -> SymptomInput extractor.

This sits between the (future) chat UI and the safety engine. It is
intentionally NOT an LLM call: the safety engine's correctness guarantees
(see app/safety/engine.py) only hold if what it receives faithfully
reflects what the patient said, and a generative extraction step would
reintroduce exactly the kind of unpredictable failure mode the rule engine
was built to avoid. Substring/keyword matching is less flexible but fully
auditable — every match traces back to one entry in symptom_phrases.py.

Known limitation (tracked, not hidden): this will miss symptom
descriptions that use wording outside SYMPTOM_PHRASES entirely. That's a
recall problem to solve by growing the phrase list (or layering an LLM
*suggestion* pass that a human reviews before adding new phrases) — not by
handing extraction to an uncontrolled model. See docs/phase2-intake-layer.md.

Negation handling (added after Phase 3 adversarial eval cases negation_01/
negation_02, then revised after a code review found two further bugs):
a naive substring match on "no chest pain" still finds the literal phrase
"chest pain". `_is_negated()` below is a small heuristic — it looks for a
negation cue word in the ~30 characters immediately before a matched
phrase, without crossing a clause boundary. It is NOT a real negation
parser (it won't handle "I used to have chest pain but not anymore", or
negation cues further back than the window) — it closes the specific
cases that were found, not negation in general. Remaining gaps here would
show up as new adversarial eval cases, same as any other extractor
limitation.

Two bugs fixed in the code-review pass:
  1. `_match_symptom_ids` used `text.find(phrase)`, which only locates the
     FIRST occurrence of a phrase — if that occurrence was negated, a
     later AFFIRMED occurrence of the same phrase later in the message
     was never checked (e.g. "No chest pain earlier, but now I have
     severe chest pain" never detected chest_pain at all). Fixed by
     scanning every occurrence of a phrase and matching if ANY of them is
     un-negated.
  2. `_is_negated` matched cues as literal substrings requiring exact
     spacing (e.g. "no " with a trailing space), so "No, chest pain."
     never matched the "no " cue at all (there's a comma, not a space,
     right after "no") and the denial was missed entirely. Fixed by
     matching cues as whole words via regex (`\bno\b` etc), which is
     insensitive to trailing punctuation, combined with treating a
     clause-boundary character as ending the negation's scope only when
     something appears between the cue and that boundary — so "No,
     chest pain" (comma immediately after the cue, nothing else) still
     counts as negating "chest pain", while "no history of asthma. chest
     pain started..." (real content, then a period, before the target
     phrase) correctly does not.

Internationalization (Phase 05 epic): every function below now takes an
optional `language` (default "en"), and looks up its phrase/cue lists
from `PHRASES_BY_LANGUAGE[language]` instead of the old fixed top-level
constants. This is the actual safety-critical half of i18n — see
symptom_phrases.py's docstring. Age-phrase regexes (`_AGE_YEARS_RE` /
`_AGE_MONTHS_RE`) are NOT yet localized (they assume English "N year(s)
old" / "N month(s) old" phrasing) — a known, documented gap for Spanish
input (see docs/phase9b-internationalization.md), not a silent one.
"""

from __future__ import annotations

import re
from functools import cache

from app.intake.symptom_phrases import DEFAULT_LANGUAGE, PHRASES_BY_LANGUAGE
from app.safety.schemas import OnsetSpeed, PatientContext, Severity, SymptomInput

_AGE_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-\s]?year[s]?[-\s]?old")
_AGE_MONTHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-\s]?month[s]?[-\s]?old")
# Added after the adversarial eval suite found a real, dangerous gap: an
# infant's age stated in weeks ("10 weeks old") wasn't parsed at all, so
# the infant_high_fever rule's age_years_max gate silently never fired
# for a real newborn/young-infant fever — exactly the population that
# gate exists to protect. See docs/phase10b-expanded-eval-and-load-testing.md.
_AGE_WEEKS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-\s]?week[s]?[-\s]?old")

_NEGATION_WINDOW_CHARS = 30
_CLAUSE_BOUNDARY_CHARS = (".", ",", ";")


@cache
def _negation_patterns(language: str) -> tuple[re.Pattern, ...]:
    cues = PHRASES_BY_LANGUAGE[language]["negation_cues"]
    return tuple(re.compile(cue) for cue in cues)


def _normalize(text: str) -> str:
    return text.lower().strip()


def _is_negated(text: str, phrase_start: int, language: str) -> bool:
    window_start = max(0, phrase_start - _NEGATION_WINDOW_CHARS)
    preceding = text[window_start:phrase_start]

    for pattern in _negation_patterns(language):
        for match in pattern.finditer(preceding):
            # Everything between the end of this cue and the phrase start.
            # A leading pause (", " right after "No") doesn't end the
            # negation's scope — only a boundary with real content before
            # it does (a genuinely separate clause/sentence).
            between = preceding[match.end():].lstrip(" " + "".join(_CLAUSE_BOUNDARY_CHARS))
            if not any(b in between for b in _CLAUSE_BOUNDARY_CHARS):
                return True
    return False


def _any_phrase_affirmed(text: str, phrases: list[str], language: str) -> bool:
    """True if any of `phrases` appears in `text` in an un-negated
    occurrence. Scans every occurrence of each phrase (not just the
    first) and accepts if ANY is un-negated — the same "a later,
    affirmed mention shouldn't be shadowed by an earlier negated one"
    logic _match_symptom_ids has always used, now shared with
    _match_context below (see that function for why sharing this
    mattered: context flags had NO negation handling at all until this
    was extracted, a real bug the adversarial eval suite found — "I'm
    not pregnant, just have a headache" incorrectly set is_pregnant=True).
    """
    for phrase in phrases:
        start = 0
        while True:
            idx = text.find(phrase, start)
            if idx == -1:
                break
            if not _is_negated(text, idx, language):
                return True
            start = idx + 1  # keep scanning past this negated occurrence
    return False


def _match_symptom_ids(text: str, language: str) -> list[str]:
    return [
        symptom_id
        for symptom_id, phrases in PHRASES_BY_LANGUAGE[language]["symptom"].items()
        if _any_phrase_affirmed(text, phrases, language)
    ]


def _match_severity(text: str, language: str) -> Severity:
    severity_phrases = PHRASES_BY_LANGUAGE[language]["severity"]
    # check severe/moderate/mild in that order — a text mentioning multiple
    # (e.g. "started mild but now it's severe") should take the worse case
    for label, severity in [
        ("severe", Severity.SEVERE),
        ("moderate", Severity.MODERATE),
        ("mild", Severity.MILD),
    ]:
        if any(phrase in text for phrase in severity_phrases[label]):
            return severity
    return Severity.UNKNOWN


def _match_onset(text: str, language: str) -> OnsetSpeed:
    onset_phrases = PHRASES_BY_LANGUAGE[language]["onset"]
    for label, onset in [
        ("sudden", OnsetSpeed.SUDDEN),
        ("recent", OnsetSpeed.RECENT),
        ("gradual", OnsetSpeed.GRADUAL),
        ("chronic", OnsetSpeed.CHRONIC),
    ]:
        if any(phrase in text for phrase in onset_phrases[label]):
            return onset
    return OnsetSpeed.UNKNOWN


def _extract_age_years(text: str) -> float | None:
    # English-only phrasing ("N year(s)/month(s)/week(s) old") — not yet
    # localized. See this module's docstring. Checked most-specific unit
    # first (weeks, then months, then years) since a young infant's age
    # is very commonly given in weeks, and that's exactly the population
    # infant_high_fever's age gate exists to protect — see _AGE_WEEKS_RE.
    if m := _AGE_WEEKS_RE.search(text):
        return round(float(m.group(1)) / 52, 3)
    if m := _AGE_MONTHS_RE.search(text):
        return round(float(m.group(1)) / 12, 3)
    if m := _AGE_YEARS_RE.search(text):
        return float(m.group(1))
    return None


def _match_context(text: str, language: str) -> PatientContext:
    context_phrases = PHRASES_BY_LANGUAGE[language]["context"]
    flags = {
        field: _any_phrase_affirmed(text, phrases, language)
        for field, phrases in context_phrases.items()
    }
    return PatientContext(age_years=_extract_age_years(text), **flags)


def extract_symptom_input(raw_text: str, language: str = DEFAULT_LANGUAGE) -> SymptomInput:
    if language not in PHRASES_BY_LANGUAGE:
        language = DEFAULT_LANGUAGE
    text = _normalize(raw_text)
    return SymptomInput(
        symptom_ids=_match_symptom_ids(text, language),
        severity=_match_severity(text, language),
        onset=_match_onset(text, language),
        context=_match_context(text, language),
        free_text=raw_text,
    )
