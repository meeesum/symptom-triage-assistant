"""Tests for the persistent audit trail (Phase 4).

conftest.py points DATABASE_URL at a throwaway SQLite file before any app
module is imported, so these tests never touch the real dev DB file.
"""

from sqlalchemy import select

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.safety.engine import RedFlagEngine
from app.safety.schemas import SymptomInput
from app.services.audit_log import log_triage_decision


def _count_records() -> int:
    with get_session() as session:
        return len(session.execute(select(TriageAuditRecord)).scalars().all())


def test_log_triage_decision_persists_a_record():
    before = _count_records()

    engine = RedFlagEngine()
    symptom = SymptomInput(symptom_ids=["chest_pain", "sweating"], free_text="test case")
    escalation = engine.evaluate(symptom)
    log_triage_decision(symptom, escalation, source="rule_engine_fast_path")

    after = _count_records()
    assert after == before + 1


def test_persisted_record_has_correct_fields():
    engine = RedFlagEngine()
    symptom = SymptomInput(
        symptom_ids=["cough"], severity="mild", free_text="a mild cough for the record"
    )
    escalation = engine.evaluate(symptom)
    log_triage_decision(symptom, escalation, source="rag_pipeline")

    with get_session() as session:
        latest = session.execute(
            select(TriageAuditRecord).order_by(TriageAuditRecord.id.desc())
        ).scalars().first()

    assert latest.tier == escalation.tier.value
    assert latest.matched_rule_id == escalation.matched_rule_id
    assert latest.decision_source == "rag_pipeline"
    assert latest.symptom_ids == ["cough"]
    assert latest.free_text_excerpt == "a mild cough for the record"
    assert latest.created_at is not None


def test_free_text_excerpt_is_truncated():
    engine = RedFlagEngine()
    long_text = "x" * 1000
    symptom = SymptomInput(symptom_ids=["cough"], free_text=long_text)
    escalation = engine.evaluate(symptom)
    log_triage_decision(symptom, escalation, source="rag_pipeline")

    with get_session() as session:
        latest = session.execute(
            select(TriageAuditRecord).order_by(TriageAuditRecord.id.desc())
        ).scalars().first()

    assert len(latest.free_text_excerpt) == 500
