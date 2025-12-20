"""An org_admin's self-service subscription to a recurring analytics
report, emailed on a schedule. See app/services/report_delivery.py and
docs/phase9d-reporting-exports.md.

Same lazy-row pattern as NotificationPreference: one row per user (unique
constraint on user_id), created only when a user actually subscribes — a
user who never has, simply has no row, which `is_due_for_report()`
treats as "not subscribed" rather than needing a row with an explicit
"off" value to exist for everyone.

Deliberately org_admin-only in practice (enforced in app/api/reports.py,
not here) — the roadmap's own scope is "scheduled report delivery for
org admins": an org_admin has an org-wide view (see
audit_visibility_clause's org_admin branch), which is what makes a
recurring digest actually meaningful; a `provider`'s narrower panel-based
view is already visible live on `/analytics` any time they want it.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

VALID_FREQUENCIES = ("daily", "weekly", "monthly")
VALID_FORMATS = ("csv", "pdf", "both")


class ReportSubscription(Base):
    __tablename__ = "report_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    frequency: Mapped[str] = mapped_column(String, nullable=False, default="weekly")
    report_format: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    last_sent_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
