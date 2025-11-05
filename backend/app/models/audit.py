"""Persistent audit record for every triage decision.

Privacy note (tracked, not solved here): `free_text_excerpt` stores patient-
provided text, which is exactly the kind of data a real deployment needs a
retention/encryption/access-control policy for before going anywhere near
real patients — see the Phase 0 compliance notes in the roadmap. This
table has none of that yet; it exists to prove the audit-trail shape end
to end, not as a HIPAA-ready store.

`patient_id` is nullable: most triage requests are anonymous (no login
required — see app/api/triage.py), and only get a patient_id when the
caller happened to be logged in. It's what app/api/audit.py's panel
scoping (docs/phase7a-patient-panels.md) filters on for the `provider`
role — a `NULL` row (can't be attributed to any specific patient) stays
visible to every provider regardless of panel, since restricting it
further would only make audit data disappear, not add any privacy.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TriageAuditRecord(Base):
    __tablename__ = "triage_audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    patient_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)

    symptom_ids: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    onset: Mapped[str] = mapped_column(String, nullable=False)
    free_text_excerpt: Mapped[str] = mapped_column(String, nullable=True)

    tier: Mapped[str] = mapped_column(String, nullable=False)
    matched_rule_id: Mapped[str] = mapped_column(String, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_source: Mapped[str] = mapped_column(String, nullable=False)
