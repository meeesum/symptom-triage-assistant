"""One row per retention purge run — what got deleted and when. Same
"a log that could be edited after the fact isn't a log" instinct as
AdminActionLog: this exists so "when did we last purge, and how much did
we delete" is always answerable, not just trusted to have happened. See
app/services/retention.py and docs/phase8d-retention-and-purge-jobs.md.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RetentionPurgeRun(Base):
    __tablename__ = "retention_purge_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_exchanges_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_records_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    admin_action_logs_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Added by the Phase 06 cross-phase contract-tests epic, closing a
    # real gap: purging a TriageAuditRecord used to leave any attached
    # SymptomPhoto rows (and their files on disk) orphaned, since
    # symptom photo upload (Phase 05) was built after this table and
    # was never wired back into the purge job. See
    # docs/phase10c-cross-phase-contract-tests.md.
    symptom_photos_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ran_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
