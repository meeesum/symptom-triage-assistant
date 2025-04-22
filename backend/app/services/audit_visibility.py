"""Shared visibility filter for TriageAuditRecord queries.

Extracted so GET /audit/recent (app/api/audit.py) and the analytics
endpoint (app/api/analytics.py) apply the EXACT same panel-based
visibility rule rather than two independently-maintained copies of it —
see docs/phase7a-patient-panels.md for what the rule actually is and why.

`org_admin` support was added in docs/phase8c-admin-action-audit-log.md,
closing a gap that doc names explicitly: six endpoints using this clause
were left gating on `require_role("provider", "admin")` from before
`org_admin` existed (docs/phase8a-organizations.md), so an `org_admin`
got a flat 403 on all of them despite app/models/user.py's own docstring
describing the role as "a strict superset within their own org." An
`org_admin` sees every patient in their OWN organization (not just a
provider's own panel — org_admin is administrative, not clinical, so
"their panel" isn't the right boundary) plus every anonymous record, same
as everyone else.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select

from app.models.audit import TriageAuditRecord
from app.models.user import User
from app.services.patient_panel import list_panel_patient_ids


def audit_visibility_clause(
    role: str, user_id: int, org_id: int | None = None
) -> ColumnElement[bool] | None:
    """A SQLAlchemy boolean clause to AND onto a TriageAuditRecord query,
    or None if the role is unrestricted (platform admin — every other
    role that isn't `provider`/`org_admin` is expected to never reach a
    query using this at all, since the routes calling this already gate
    on require_role(...) accordingly).

    org_id is required (and used) only for `org_admin`; callers for other
    roles may omit it."""
    if role == "org_admin":
        patient_ids_in_org = select(User.id).where(User.org_id == org_id, User.role == "patient")
        return or_(
            TriageAuditRecord.patient_id.is_(None),
            TriageAuditRecord.patient_id.in_(patient_ids_in_org),
        )

    if role != "provider":
        return None

    panel_patient_ids = list_panel_patient_ids(user_id)
    if panel_patient_ids:
        return or_(
            TriageAuditRecord.patient_id.is_(None),
            TriageAuditRecord.patient_id.in_(panel_patient_ids),
        )
    return TriageAuditRecord.patient_id.is_(None)
