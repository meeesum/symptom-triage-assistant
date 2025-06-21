"""A patient-uploaded photo attached to a triage audit record (e.g. a
photo of a rash).

`audit_record_id` is a plain Integer, not a SQLAlchemy ForeignKey — same
"no FK constraint enforcement" pattern as every other cross-table
reference in this codebase (see ClinicalNote's docstring).

A photo's visibility follows the exact same rule as the audit record it's
attached to (patient panel scoping — see app/services/patient_panel.py),
same reuse pattern ClinicalNote and Referral already established.
Uploading, unlike clinical notes, is patient-initiated, not
provider-initiated — see app/services/symptom_photos.py and
docs/phase9c-symptom-photo-upload.md.

`storage_filename` is a server-generated, random name (never derived from
the client-supplied filename or content) — see
app/services/symptom_photos.py's save_photo() for why: trusting a
client-supplied filename for an on-disk path is a path-traversal /
overwrite risk this table's own column intentionally avoids by
construction, not just by validation.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SymptomPhoto(Base):
    __tablename__ = "symptom_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    storage_filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
