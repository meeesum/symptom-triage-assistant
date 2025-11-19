"""High-risk alerting — decouples "page the on-call provider" from the
request/response cycle of an emergency-tier triage, via a real job queue
(RQ) instead of doing the paging work inline. See
docs/phase7e-high-risk-alerting.md.

Two-phase, same "cheap synchronous record, expensive work deferred"
split as everywhere else safety-critical in this codebase:

  1. trigger_high_risk_alert() runs INLINE in the triage request path —
     one fast INSERT (status="queued") plus an enqueue call. Wrapped in
     try/except: alerting must never be able to delay or break an
     emergency-tier response, the same principle audit logging already
     follows (app/services/audit_log.py) — an alerting outage should
     degrade to "no page went out" (loud, in logs), never "the patient's
     emergency response failed because paging failed."
  2. process_alert() is the actual job — resolves an on-call recipient
     (the first provider on the patient's panel, if the patient is
     identifiable and has one), marks the alert sent, and dispatches a
     real notification to that recipient via
     app/services/notifications.py (email/SMS, per that provider's own
     preferences — see docs/phase7f-notifications.md). A notification
     delivery failure never rolls back the alert's "sent" status — the
     durable, queryable Alert record is what must not be lost; a failed
     email/SMS is a delivery-channel problem, logged loudly on its own.

ALERTING_SYNC=1 (set by default in tests/conftest.py) runs the queue in
RQ's `is_async=False` mode: enqueue() executes process_alert() inline,
in-process, no separate worker needed — deterministic and fast for
tests. Unset (the app's real default), a job sits on a real Redis-backed
queue until an actual `rq worker high_risk_alerts` process picks it up —
a genuine new operational requirement for a deployment enabling this
feature, not just a nicety. See docs/phase7e for how this was verified
against a real worker process, since none can run persistently in this
sandbox.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from rq import Queue

from app.core.db import get_session
from app.core.queue_client import queue_redis_client
from app.models.alert import Alert
from app.models.audit import TriageAuditRecord
from app.services.notifications import notify_user
from app.services.patient_panel import list_assigned_providers

logger = logging.getLogger("triage.alerting")

QUEUE_NAME = "high_risk_alerts"


def _is_sync() -> bool:
    return os.environ.get("ALERTING_SYNC") == "1"


def get_alert_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=queue_redis_client, is_async=not _is_sync())


def trigger_high_risk_alert(audit_record_id: int, message: str) -> Alert | None:
    try:
        with get_session() as session:
            alert = Alert(audit_record_id=audit_record_id, status="queued", message=message)
            session.add(alert)
            session.commit()
            session.refresh(alert)
            alert_id = alert.id
            session.expunge(alert)
    except Exception:
        logger.exception("Failed to create alert record for audit record %s", audit_record_id)
        return None

    try:
        get_alert_queue().enqueue(process_alert, alert_id)
    except Exception:
        logger.exception("Failed to enqueue high-risk alert %s", alert_id)

    return alert


def process_alert(alert_id: int) -> None:
    """The actual job body — must be a top-level, importable function
    (not a closure/lambda), since RQ resolves it by import path when a
    real worker process picks the job up from the queue."""
    with get_session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            logger.warning("process_alert: no such alert %s", alert_id)
            return

        record = session.get(TriageAuditRecord, alert.audit_record_id)
        recipient_provider_id = None
        if record is not None and record.patient_id is not None:
            providers = list_assigned_providers(record.patient_id)
            recipient_provider_id = providers[0] if providers else None

        alert.recipient_provider_id = recipient_provider_id
        alert.status = "sent"
        alert.sent_at = datetime.now(UTC)
        alert_message = alert.message
        session.commit()

    logger.info(
        "high_risk_alert_sent",
        extra={"alert_id": alert_id, "recipient_provider_id": recipient_provider_id},
    )

    if recipient_provider_id is not None:
        # See app/services/notifications.py — never raises, and any
        # failure here doesn't roll back the alert's "sent" status above:
        # the alert itself (a durable, queryable record a provider can
        # check via GET /alerts/recent) is the thing that must not be
        # lost. A failed email/SMS is a delivery-channel problem, logged
        # loudly by notify_user() itself, not a reason to leave the alert
        # stuck at "sent but we're not sure it happened."
        notify_user(recipient_provider_id, subject="High-risk triage alert", message=alert_message)
