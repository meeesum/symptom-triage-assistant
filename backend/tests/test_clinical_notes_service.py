import pytest

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.services.clinical_notes import (
    AuditRecordNotFound,
    add_note,
    get_audit_record_patient_id,
    list_notes,
)


def _create_audit_record(patient_id: int | None = None) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["cough"],
            severity="mild",
            onset="gradual",
            tier="routine",
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_get_audit_record_patient_id_returns_none_for_anonymous_record():
    record_id = _create_audit_record(patient_id=None)
    assert get_audit_record_patient_id(record_id) is None


def test_get_audit_record_patient_id_returns_the_patient_id():
    record_id = _create_audit_record(patient_id=42)
    assert get_audit_record_patient_id(record_id) == 42


def test_get_audit_record_patient_id_raises_for_unknown_record():
    with pytest.raises(AuditRecordNotFound):
        get_audit_record_patient_id(999999)


def test_add_note_and_list_notes():
    record_id = _create_audit_record()
    add_note(record_id, author_id=7, body="Discussed with patient by phone.", note_type="general")
    add_note(record_id, author_id=7, body="Recommend follow-up in 1 week.", note_type="follow_up")

    notes = list_notes(record_id)
    assert len(notes) == 2
    assert notes[0].body == "Discussed with patient by phone."
    assert notes[1].note_type == "follow_up"


def test_list_notes_empty_for_record_with_no_notes():
    record_id = _create_audit_record()
    assert list_notes(record_id) == []


def test_notes_are_scoped_to_their_own_audit_record():
    record_a = _create_audit_record()
    record_b = _create_audit_record()
    add_note(record_a, author_id=1, body="Note on A.", note_type="general")

    assert len(list_notes(record_a)) == 1
    assert list_notes(record_b) == []
