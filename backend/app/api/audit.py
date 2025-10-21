"""Read-only audit trail endpoint.

Gated to provider/admin roles (see app/api/deps.py::require_role) — the
seed of the future Phase 4 provider dashboard. Still missing: rate
limiting on this route specifically (the app-wide auth-endpoint limits
from Phase 5d don't cover this one).

Per-row access scoping IS now wired in (docs/phase7a-patient-panels.md):
a `provider` only sees rows for patients on their own panel (see
app/services/patient_panel.py), plus every row with no `patient_id` at
all (an anonymous triage request — not attributable to any specific
patient, so restricting it further by panel would only hide audit data,
not protect anyone's privacy). An `org_admin` sees every patient in their
own org (docs/phase8c-admin-action-audit-log.md). Platform `admin` is
unrestricted, a strict superset — same relationship documented in
app/models/user.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, require_role
from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.services.audit_visibility import audit_visibility_clause

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/recent")
async def recent_audit_records(
    limit: int = 50,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> list[dict]:
    # Floor AND ceiling — limit=0 used to silently return zero rows
    # (indistinguishable from "no audit records exist") and a negative
    # limit passed straight through to SQLAlchemy's .limit(), which is
    # backend-dependent and could raise. Caught during the chat-history
    # feature, which needed the same clamp and made the gap here obvious.
    limit = min(max(limit, 1), 200)
    with get_session() as session:
        query = select(TriageAuditRecord).order_by(TriageAuditRecord.id.desc()).limit(limit)

        visibility = audit_visibility_clause(user.role, user.id, user.org_id)
        if visibility is not None:
            query = query.where(visibility)

        rows = session.execute(query).scalars().all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "symptom_ids": r.symptom_ids,
                "severity": r.severity,
                "onset": r.onset,
                "tier": r.tier,
                "matched_rule_id": r.matched_rule_id,
                "requires_human_review": r.requires_human_review,
                "decision_source": r.decision_source,
            }
            for r in rows
        ]
