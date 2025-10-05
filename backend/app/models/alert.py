"""High-risk alert record — one row per emergency-tier triage decision
that triggered an on-call page. See app/services/alerting.py and
docs/phase7e-high-risk-alerting.md.

Created (status="queued") synchronously in the request path — cheap, a
single INSERT, same principle as the audit trail itself: the ALERT
existing is not optional, but actually PAGING someone is decoupled onto
the job queue so a slow/failing notification integration can never delay
or break an emergency-tier triage response.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

VALID_ALERT_STATUSES = ("queued", "sent", "failed")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    message: Mapped[str] = mapped_column(String, nullable=False)
    recipient_provider_id: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)
