"""Core data types for the deterministic safety layer.

This layer is intentionally independent of the LLM/RAG pipeline. It must be
able to make an escalation decision using nothing but rule matching, so that
its correctness can be unit tested exhaustively and does not depend on model
behavior, prompt wording, or retrieval quality.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EscalationTier(StrEnum):
    EMERGENCY = "emergency"          # call emergency services / ER now
    URGENT = "urgent"                # seek care within hours (urgent care / same-day)
    ROUTINE = "routine"               # schedule a visit within days
    SELF_CARE = "self_care"           # self-manage, monitor for change


class Severity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class OnsetSpeed(StrEnum):
    SUDDEN = "sudden"        # minutes
    RECENT = "recent"        # hours to a couple days
    GRADUAL = "gradual"      # days to weeks
    CHRONIC = "chronic"      # weeks+
    UNKNOWN = "unknown"


class PatientContext(BaseModel):
    """Demographic/context fields that change risk thresholds.

    Kept minimal on purpose — every field added here must correspond to an
    actual rule that uses it (see rules.yaml), otherwise it's dead weight
    collected from the patient for no reason.
    """

    age_years: float | None = Field(
        default=None, ge=0, le=130,
        description="Fractional years — e.g. a 3-month-old infant is 0.25",
    )
    is_pregnant: bool = False
    has_cardiac_history: bool = False
    has_respiratory_history: bool = False
    is_immunocompromised: bool = False


class SymptomInput(BaseModel):
    """Structured intake — the conversational layer maps free text onto this
    before it ever reaches the safety engine. The safety engine never sees
    raw chat text directly."""

    symptom_ids: list[str] = Field(
        default_factory=list,
        description="Normalized symptom identifiers, e.g. 'chest_pain', 'shortness_of_breath'",
    )
    severity: Severity = Severity.UNKNOWN
    onset: OnsetSpeed = OnsetSpeed.UNKNOWN
    duration_hours: float | None = None
    context: PatientContext = Field(default_factory=PatientContext)
    free_text: str = ""  # retained only for audit logging / later RAG grounding


class EscalationResult(BaseModel):
    tier: EscalationTier
    reason: str
    matched_rule_id: str | None = None
    guidance: str
    requires_human_review: bool = False
