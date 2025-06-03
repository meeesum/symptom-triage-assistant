"""Records an admin/provider action. Same "logging must never break the
real action" principle as app/services/audit_log.py's
log_triage_decision() — wrapped in try/except, logged at ERROR on
failure rather than propagating, since a logging outage should never be
able to block a role change, a panel assignment, or a KB review
decision. See app/models/admin_action_log.py and
docs/phase8c-admin-action-audit-log.md for what gets logged and why.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.db import get_session
from app.models.admin_action_log import AdminActionLog

logger = logging.getLogger("triage.admin_action_log")


def log_admin_action(
    actor_id: int,
    actor_role: str,
    actor_org_id: int,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    detail: dict | None = None,
) -> None:
    logger.info(
        "admin_action",
        extra={
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
    try:
        with get_session() as session:
            session.add(
                AdminActionLog(
                    actor_id=actor_id,
                    actor_role=actor_role,
                    actor_org_id=actor_org_id,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    detail=detail or {},
                )
            )
            session.commit()
    except Exception:
        logger.exception("Failed to persist admin action log — stdout log above is the only copy")


def list_actions(org_id: int | None = None, limit: int = 100) -> list[AdminActionLog]:
    """org_id=None (platform admin) lists every org's actions. Otherwise
    (org_admin) scoped to actions taken BY that org's own actors —
    mirrors app/services/patient_panel.py's list_all_assignments()."""
    with get_session() as session:
        query = select(AdminActionLog).order_by(AdminActionLog.id.desc()).limit(limit)
        if org_id is not None:
            query = query.where(AdminActionLog.actor_org_id == org_id)
        rows = session.execute(query).scalars().all()
        for row in rows:
            session.expunge(row)
        return rows
