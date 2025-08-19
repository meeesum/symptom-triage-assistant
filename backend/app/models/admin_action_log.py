"""A second, narrower audit trail than TriageAuditRecord (app/models/audit.py)
— that one records clinical triage DECISIONS; this one records actions
taken by the platform's own admins/providers: who changed which role,
who assigned which provider to which patient, who approved a knowledge-
base article, who viewed which patient's clinical notes or referral.

Append-only, one row per action — same "never overwrite, always append"
instinct as ReferralStatusChange and ConsentRecord, here because the
whole point of this table is answering "who did X, when" after the fact;
an updatable log isn't a log. See app/services/admin_action_log.py and
docs/phase8c-admin-action-audit-log.md.
"""

from __future__ import annotations

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    actor_org_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
