"""Provider-patient panel assignment.

Closes the gap app/api/audit.py's own docstring has flagged since it was
first built: "a provider currently sees every patient's records, not just
their own panel." An assignment here is what scopes GET /audit/recent for
a provider (see that module) to the patients actually on their panel,
instead of every patient in the system.

Admin-controlled, not self-service — same pattern as role assignment
(app/api/admin.py): a provider doesn't add patients to their own panel: an
admin assigns them, via app/api/patient_panel.py. `provider_id`/
`patient_id` are plain Integer, not a SQLAlchemy ForeignKey, matching
every other cross-table reference in this codebase (see
ChatExchange.user_id) — no FK constraint enforcement, so pairing with an
already-deleted user id (that never happens in practice; the User model
has no delete flow) is a theoretical, accepted gap rather than a real one.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PatientPanelAssignment(Base):
    __tablename__ = "patient_panel_assignments"
    __table_args__ = (UniqueConstraint("provider_id", "patient_id", name="uq_provider_patient"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assigned_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
