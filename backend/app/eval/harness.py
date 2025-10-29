"""Adversarial eval harness: runs curated cases end-to-end through the real
intake extractor + safety engine (the same code path a request hits), and
scores them against expected escalation tiers.

This is Phase 3 of the roadmap. Its entire purpose is to actively try to
break app/intake + app/safety, not confirm they work — see
data/eval/adversarial_cases.json for the case set and
docs/phase3-adversarial-eval.md for what it found and why some cases are
tracked as known, unresolved gaps rather than hidden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.intake.extractor import extract_symptom_input
from app.safety.engine import RedFlagEngine
from app.safety.schemas import EscalationTier

_DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "eval" / "adversarial_cases.json"
)

_TIER_RANK = {
    EscalationTier.SELF_CARE: 1,
    EscalationTier.ROUTINE: 2,
    EscalationTier.URGENT: 3,
    EscalationTier.EMERGENCY: 4,
}


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    cls: str  # "must_pass" | "known_gap"
    text: str
    expected_tier: EscalationTier
    notes: str
    language: str = "en"
    # Ceiling on acceptable tier — optional, and DELIBERATELY separate from
    # expected_tier's floor semantics. Most cases only care about under-
    # triage (see EvalOutcome.under_triaged's docstring for why that
    # asymmetry is the right default): a chest-pain case that expects
    # "emergency" and a system that's even MORE cautious isn't possible
    # (emergency is already the ceiling), and for a "routine" case, getting
    # bumped to "urgent" is an acceptable safety margin, not a bug.
    # But a case whose entire point is "this must NOT be escalated"
    # (category avoid_overtriage — alarm-fatigue guards) needs its own
    # ceiling enforced, or the case is toothless: expected_tier="self_care"
    # is already the lowest rank, so under_triaged can never be True no
    # matter how badly the system over-reacts. max_tier closes that gap.
    max_tier: EscalationTier | None = None


@dataclass(frozen=True)
class EvalOutcome:
    case: EvalCase
    actual_tier: EscalationTier
    matched_rule_id: str | None

    @property
    def under_triaged(self) -> bool:
        """True if the system was LESS urgent than expected — the only
        direction that matters for safety. Over-triage (actual more urgent
        than expected) is logged but never counted as a failure."""
        return _TIER_RANK[self.actual_tier] < _TIER_RANK[self.case.expected_tier]

    @property
    def over_triaged(self) -> bool:
        """Only meaningful when the case sets max_tier — see EvalCase's
        docstring. True if the system escalated PAST the declared ceiling,
        e.g. an isolated mild symptom incorrectly landing at emergency."""
        if self.case.max_tier is None:
            return False
        return _TIER_RANK[self.actual_tier] > _TIER_RANK[self.case.max_tier]

    @property
    def exact_match(self) -> bool:
        return self.actual_tier == self.case.expected_tier


def load_cases(path: Path = _DEFAULT_CASES_PATH) -> list[EvalCase]:
    with open(path) as f:
        raw = json.load(f)
    return [
        EvalCase(
            id=c["id"],
            category=c["category"],
            cls=c["class"],
            text=c["text"],
            expected_tier=EscalationTier(c["expected_tier"]),
            notes=c["notes"],
            language=c.get("language", "en"),
            max_tier=EscalationTier(c["max_tier"]) if "max_tier" in c else None,
        )
        for c in raw["cases"]
    ]


def run_case(case: EvalCase, engine: RedFlagEngine) -> EvalOutcome:
    symptom = extract_symptom_input(case.text, language=case.language)
    result = engine.evaluate(symptom)
    return EvalOutcome(case=case, actual_tier=result.tier, matched_rule_id=result.matched_rule_id)


def run_all(path: Path = _DEFAULT_CASES_PATH) -> list[EvalOutcome]:
    engine = RedFlagEngine()
    return [run_case(c, engine) for c in load_cases(path)]
