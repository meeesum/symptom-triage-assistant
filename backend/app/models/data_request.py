"""GDPR/HIPAA-style data subject requests — export ("what do you have on
me") and deletion ("erase what you have on me"). One row per request,
append-only audit trail of who asked for what and when — see
app/services/data_rights.py and docs/phase8b-consent-and-data-rights.md
for what "deletion" actually does (anonymization, not a hard DELETE of
the account — a deliberate choice, not a shortcut).
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

REQUEST_TYPES = ("export", "deletion")
REQUEST_STATUSES = ("completed", "failed")


class DataRequest(Base):
    __tablename__ = "data_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
