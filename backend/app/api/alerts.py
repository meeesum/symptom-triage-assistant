"""Read-only view of high-risk alerts — oversight for provider/admin,
same panel-based visibility as GET /audit/recent: a provider only sees
alerts for audit records they could see there (their panel, or an
anonymous record). See app/services/alerting.py and
docs/phase7e-high-risk-alerting.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, require_role
from app.core.db import get_session
from app.models.alert import Alert
from app.models.audit import TriageAuditRecord
from app.services.audit_visibility import audit_visibility_clause

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/recent")
async def recent_alerts(
    limit: int = 50,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> list[dict]:
    limit = min(max(limit, 1), 200)  # same floor-and-ceiling pattern as GET /audit/recent
    with get_session() as session:
        query = (
            select(Alert)
            .join(TriageAuditRecord, Alert.audit_record_id == TriageAuditRecord.id)
            .order_by(Alert.id.desc())
            .limit(limit)
        )
        visibility = audit_visibility_clause(user.role, user.id, user.org_id)
        if visibility is not None:
            query = query.where(visibility)

        rows = session.execute(query).scalars().all()
        return [
            {
                "id": a.id,
                "audit_record_id": a.audit_record_id,
                "status": a.status,
                "message": a.message,
                "recipient_provider_id": a.recipient_provider_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            }
            for a in rows
        ]
