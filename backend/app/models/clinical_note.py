"""Provider annotations on a triage audit record.

`audit_record_id` is a plain Integer, not a SQLAlchemy ForeignKey — same
"no FK constraint enforcement" pattern as PatientPanelAssignment (see its
docstring) and every other cross-table reference in this codebase.

A note's visibility follows the same rule as the audit record it's
attached to (see app/services/patient_panel.py's
provider_can_view_record()): if a provider can't see the record via
GET /audit/recent, they can't see or add notes on it either. See
docs/phase7b-clinical-notes.md.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

VALID_NOTE_TYPES = ("clinical_impression", "follow_up", "general")


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(Integer, nullable=False)
    note_type: Mapped[str] = mapped_column(String, nullable=False, default="general")
    body: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
