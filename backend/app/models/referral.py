"""Referral & appointment tracking — a lightweight status model a
provider moves a case through after a triage result: referred ->
scheduled -> seen. See docs/phase7c-referral-tracking.md.

One `Referral` per audit record (unique constraint on `audit_record_id`)
— this is "the case," not a log of separate referral events. Every
status transition is additionally recorded in `ReferralStatusChange`,
append-only, so "who moved this to `seen` and when" is always
answerable — the same "never overwrite, always append" instinct as
`KbArticleSubmission`'s version history (docs/phase6e), just applied to
status instead of content.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUS_ORDER = ("referred", "scheduled", "seen")


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_record_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="referred")
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReferralStatusChange(Base):
    __tablename__ = "referral_status_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
