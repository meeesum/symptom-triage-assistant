"""Deterministic red-flag / escalation engine.

Design intent (see docs/phase2-safety-engine.md for the full rationale):

  - This engine is a pure function of structured input -> EscalationResult.
    No network calls, no LLM, no randomness. That's what makes it exhaustively
    unit-testable and auditable.
  - It is evaluated BEFORE the RAG/LLM pipeline ever runs. If it returns
    "emergency" or "urgent", the API layer short-circuits and returns the
    rule-based guidance directly — the LLM is not in the loop for the
    highest-risk decisions.
  - Rules are data (rules.yaml), not code, so a clinical reviewer can audit
    or extend them without touching Python.
  - Rule order matters: first match wins, and rules.yaml is ordered
    emergency -> urgent -> routine -> self_care. This means an emergency
    combination is always caught even if a lower-tier rule would also match
    the same symptom in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.safety.schemas import (
    EscalationResult,
    EscalationTier,
    Severity,
    SymptomInput,
)

_SEVERITY_ORDER = {
    Severity.MILD: 1,
    Severity.MODERATE: 2,
    Severity.SEVERE: 3,
}

_DEFAULT_RULES_PATH = Path(__file__).parent / "rules.yaml"

_DEFAULT_UNMATCHED_GUIDANCE = (
    "We couldn't confidently match your symptoms to a specific guidance "
    "pattern. To be safe, please contact a healthcare provider to discuss "
    "your symptoms, or seek urgent care if anything feels severe or is "
    "rapidly worsening."
)


@dataclass(frozen=True)
class Rule:
    id: str
    tier: EscalationTier
    description: str
    any_of: tuple[str, ...]
    all_of: tuple[str, ...]
    severity_at_least: Severity | None
    onset_in: tuple[str, ...]
    context_conditions: dict[str, Any]
    guidance: str
    requires_human_review: bool

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> Rule:
        match = raw.get("match", {})
        conditions = raw.get("conditions", {})
        return Rule(
            id=raw["id"],
            tier=EscalationTier(raw["tier"]),
            description=raw.get("description", ""),
            any_of=tuple(match.get("any_of", [])),
            all_of=tuple(match.get("all_of", [])),
            severity_at_least=(
                Severity(conditions["severity_at_least"])
                if "severity_at_least" in conditions
                else None
            ),
            onset_in=tuple(conditions.get("onset_in", [])),
            context_conditions=conditions.get("context", {}),
            guidance=str(raw["guidance"]).strip(),
            requires_human_review=bool(raw.get("requires_human_review", False)),
        )


def load_rules(path: Path = _DEFAULT_RULES_PATH) -> list[Rule]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return [Rule.from_dict(r) for r in raw["rules"]]


def _meets_severity(symptom: SymptomInput, threshold: Severity | None) -> bool:
    if threshold is None:
        return True
    if symptom.severity == Severity.UNKNOWN:
        # Unknown severity never satisfies a minimum-severity gate — we don't
        # downgrade risk based on absence of information, but we also don't
        # claim a severity threshold was met when it wasn't reported.
        return False
    return _SEVERITY_ORDER[symptom.severity] >= _SEVERITY_ORDER[threshold]


def _meets_onset(symptom: SymptomInput, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return True
    return symptom.onset.value in allowed


def _meets_context(symptom: SymptomInput, conditions: dict[str, Any]) -> bool:
    ctx = symptom.context
    for key, expected in conditions.items():
        if key == "age_years_max":
            if ctx.age_years is None or ctx.age_years > expected:
                return False
        elif key == "age_years_min":
            if ctx.age_years is None or ctx.age_years < expected:
                return False
        elif hasattr(ctx, key):
            if getattr(ctx, key) != expected:
                return False
        else:
            raise ValueError(f"Unknown context condition key: {key}")
    return True


def _matches(symptom: SymptomInput, rule: Rule) -> bool:
    present = set(symptom.symptom_ids)

    if rule.all_of and not set(rule.all_of).issubset(present):
        return False

    if rule.any_of and not (present & set(rule.any_of)):
        return False

    if not rule.all_of and not rule.any_of:
        return False  # a rule with no match criteria is a config error, never auto-match

    if not _meets_severity(symptom, rule.severity_at_least):
        return False
    if not _meets_onset(symptom, rule.onset_in):
        return False
    return _meets_context(symptom, rule.context_conditions)


class RedFlagEngine:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules if rules is not None else load_rules()

    def evaluate(self, symptom: SymptomInput) -> EscalationResult:
        for rule in self.rules:
            if _matches(symptom, rule):
                return EscalationResult(
                    tier=rule.tier,
                    reason=rule.description,
                    matched_rule_id=rule.id,
                    guidance=rule.guidance,
                    requires_human_review=rule.requires_human_review,
                )

        # No rule matched at all. Fail safe: never claim self-care by default
        # for something we couldn't classify — route to routine-at-minimum
        # guidance and let the RAG layer add context on top of it.
        return EscalationResult(
            tier=EscalationTier.ROUTINE,
            reason="No matching rule — unclassified symptom pattern",
            matched_rule_id=None,
            guidance=_DEFAULT_UNMATCHED_GUIDANCE,
            requires_human_review=False,
        )
