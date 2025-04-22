"""Consent recording/reading. See app/models/consent.py for why this is
append-only, and docs/phase8b-consent-and-data-rights.md for the design.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import get_session
from app.models.consent import ConsentRecord


def record_consent(user_id: int, consent_type: str, granted: bool) -> ConsentRecord:
    with get_session() as session:
        record = ConsentRecord(user_id=user_id, consent_type=consent_type, granted=granted)
        session.add(record)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record


def get_current_consent(user_id: int, consent_type: str) -> ConsentRecord | None:
    """The most recent record for this (user, consent_type) pair — a
    consent history can have many rows; this is what's CURRENTLY true."""
    with get_session() as session:
        record = session.execute(
            select(ConsentRecord)
            .where(ConsentRecord.user_id == user_id, ConsentRecord.consent_type == consent_type)
            .order_by(ConsentRecord.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if record is not None:
            session.expunge(record)
        return record


def has_consented(user_id: int, consent_type: str) -> bool:
    current = get_current_consent(user_id, consent_type)
    return current is not None and current.granted


def get_consent_history(user_id: int) -> list[ConsentRecord]:
    with get_session() as session:
        rows = (
            session.execute(
                select(ConsentRecord)
                .where(ConsentRecord.user_id == user_id)
                .order_by(ConsentRecord.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows
