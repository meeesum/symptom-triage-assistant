"""Phase 3 adversarial eval — wired into the normal test suite so
under-triage regressions on must_pass cases fail CI, not just a manual
script run.

known_gap cases are wrapped in strict xfail: if one starts passing, the
test suite FAILS (not silently passes) until the case is reclassified to
must_pass and the docs/case notes are updated. This exists specifically so
a fixed gap can't quietly stop being tracked.
"""

import pytest

from app.eval.harness import load_cases, run_case
from app.safety.engine import RedFlagEngine

_ENGINE = RedFlagEngine()
_ALL_CASES = load_cases()

_MUST_PASS = [c for c in _ALL_CASES if c.cls == "must_pass"]
_KNOWN_GAP = [c for c in _ALL_CASES if c.cls == "known_gap"]


@pytest.mark.parametrize("case", _MUST_PASS, ids=[c.id for c in _MUST_PASS])
def test_must_pass_case_never_under_triages(case):
    outcome = run_case(case, _ENGINE)
    assert not outcome.under_triaged, (
        f"[{case.id}] under-triaged: expected >= {case.expected_tier.value}, "
        f"got {outcome.actual_tier.value}. text: {case.text!r}. notes: {case.notes}"
    )
    # Only a subset of cases set max_tier (see EvalCase's docstring in
    # app/eval/harness.py) — over_triaged is False by construction for
    # every case that doesn't, so this assertion is a no-op for them.
    assert not outcome.over_triaged, (
        f"[{case.id}] over-triaged: expected <= {case.max_tier.value if case.max_tier else '?'}, "
        f"got {outcome.actual_tier.value}. text: {case.text!r}. notes: {case.notes}"
    )


@pytest.mark.parametrize("case", _KNOWN_GAP, ids=[c.id for c in _KNOWN_GAP])
@pytest.mark.xfail(strict=True, reason="documented known gap — see data/eval/adversarial_cases.json notes")
def test_known_gap_case_still_fails_as_documented(case):
    outcome = run_case(case, _ENGINE)
    assert outcome.exact_match, (
        f"[{case.id}] expected {case.expected_tier.value}, got {outcome.actual_tier.value}"
    )


def test_eval_case_set_has_both_classes_represented():
    # sanity check on the eval set itself, not the system under test
    assert _MUST_PASS, "no must_pass cases — eval suite would be a no-op gate"
    assert _KNOWN_GAP, "no known_gap cases — either everything's fixed (update docs) or none are tracked"
