"""Clinical note creation/reading. See app/models/clinical_note.py and
docs/phase7b-clinical-notes.md for the design rationale.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.models.clinical_note import ClinicalNote


class AuditRecordNotFound(Exception):
    pass


def get_audit_record_patient_id(audit_record_id: int) -> int | None:
    """Raises AuditRecordNotFound if the record doesn't exist at all —
    distinct from returning None, which means "exists, but anonymous"."""
    with get_session() as session:
        record = session.get(TriageAuditRecord, audit_record_id)
        if record is None:
            raise AuditRecordNotFound(f"no audit record with id {audit_record_id}")
        return record.patient_id


def add_note(audit_record_id: int, author_id: int, body: str, note_type: str) -> ClinicalNote:
    with get_session() as session:
        note = ClinicalNote(
            audit_record_id=audit_record_id,
            author_id=author_id,
            note_type=note_type,
            body=body,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        session.expunge(note)
        return note


def list_notes(audit_record_id: int) -> list[ClinicalNote]:
    with get_session() as session:
        rows = (
            session.execute(
                select(ClinicalNote)
                .where(ClinicalNote.audit_record_id == audit_record_id)
                .order_by(ClinicalNote.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows
