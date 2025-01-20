"""Persisted triage chat history — one row per patient message + response.

Only saved for logged-in patients (see app/api/triage.py's use of
get_optional_current_user) — anonymous triage requests are never
persisted here, same privacy stance already taken for audit records'
free-text excerpt (see app/models/audit.py). This is a separate table
from TriageAuditRecord: the audit trail exists for clinical/compliance
review and is provider/admin-readable; this table exists so a patient can
see their own past conversation, and only that patient (and nothing here
is exposed to providers) can read it.
"""

from __future__ import annotations

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatExchange(Base):
    __tablename__ = "chat_exchanges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user_text: Mapped[str] = mapped_column(String, nullable=False)

    tier: Mapped[str] = mapped_column(String, nullable=False)
    guidance: Mapped[str] = mapped_column(String, nullable=False)
    matched_rule_id: Mapped[str] = mapped_column(String, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(default=False)
    sources: Mapped[list] = mapped_column(JSON, default=list)

    understood_symptom_ids: Mapped[list] = mapped_column(JSON, default=list)
    understood_severity: Mapped[str] = mapped_column(String, nullable=True)
    understood_onset: Mapped[str] = mapped_column(String, nullable=True)
