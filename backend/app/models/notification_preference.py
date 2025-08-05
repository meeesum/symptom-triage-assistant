"""Per-user notification preferences — which channels (email/SMS) a user
wants high-risk alerts delivered through, and the phone number to use for
SMS (email reuses the account's existing User.email — no separate field
needed). Self-service, unlike patient-panel/role assignment: a user's own
notification preferences are personal, not an assignment or permission,
so app/api/notifications.py lets the CURRENT user manage their own rather
than gating this admin-only. See docs/phase7f-notifications.md.

One row per user (unique constraint on user_id), created lazily on first
write — a user who never sets preferences gets sensible defaults (email
on, SMS off) from app/services/notifications.py rather than needing a row
to exist at all.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phone_number: Mapped[str] = mapped_column(String, nullable=True)
