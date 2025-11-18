"""Audit logging for triage decisions.

Every triage decision must be logged regardless of outcome — this is the
record that lets a clinical reviewer later audit false negatives/positives,
and it's required groundwork for any future compliance review.

Writes to both: stdout (structured logging, always — cheap, and useful for
local debugging/log aggregation) and a persistent DB table (see
app/models/audit.py). The DB write is wrapped so a DB outage degrades to
stdout-only rather than breaking a triage response — audit logging must
never be able to block or fail an emergency-tier response, which is
exactly the kind of coupling that would turn an infra hiccup into a safety
incident. The failure is not silent: it's logged at ERROR level so it
surfaces in monitoring instead of failing the request.
"""

from __future__ import annotations

import logging

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.safety.schemas import EscalationResult, SymptomInput

logger = logging.getLogger("triage.audit")

_FREE_TEXT_EXCERPT_MAX_CHARS = 500


def log_triage_decision(
    symptom: SymptomInput,
    escalation: EscalationResult,
    source: str,
    patient_id: int | None = None,
) -> int | None:
    """Returns the new TriageAuditRecord's id, or None if the DB write
    failed (stdout log is still the record of what happened — see below).
    app/api/triage.py uses this id to link a high-risk alert
    (app/services/alerting.py) to the record that triggered it."""
    logger.info(
        "triage_decision",
        extra={
            "symptom_ids": symptom.symptom_ids,
            "severity": symptom.severity.value,
            "onset": symptom.onset.value,
            "tier": escalation.tier.value,
            "matched_rule_id": escalation.matched_rule_id,
            "requires_human_review": escalation.requires_human_review,
            "decision_source": source,
        },
    )

    try:
        with get_session() as session:
            record = TriageAuditRecord(
                patient_id=patient_id,
                symptom_ids=symptom.symptom_ids,
                severity=symptom.severity.value,
                onset=symptom.onset.value,
                free_text_excerpt=symptom.free_text[:_FREE_TEXT_EXCERPT_MAX_CHARS],
                tier=escalation.tier.value,
                matched_rule_id=escalation.matched_rule_id,
                requires_human_review=escalation.requires_human_review,
                decision_source=source,
            )
            session.add(record)
            session.commit()
            return record.id
    except Exception:
        logger.exception("Failed to persist audit record to DB — stdout log above is the only copy")
        return None
