"""Explicit consent tracking — one row per consent DECISION, not per
user. A user's current status for a given consent_type is "whatever the
most recent row says" (see app/services/consent.py), so granting then
later withdrawing consent is a new row, not an update — the same
"never overwrite, always append" instinct as KbArticleSubmission's
version history and ReferralStatusChange, applied here because a consent
history (who agreed to what, when, and whether they later withdrew it) is
itself the kind of record a real compliance review needs to exist.

CONSENT_TYPES is deliberately a small, fixed set rather than a free-text
field — each one corresponds to an actual thing this product does with
personal data, not a guess at future ones. See
docs/phase8b-consent-and-data-rights.md.
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CONSENT_TYPES = ("data_processing", "marketing_communications")


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String, nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
