"""Scheduled analytics report delivery — the roadmap's "scheduled report
delivery for org admins" half of this epic (the on-demand CSV/PDF export
endpoints live in app/api/reports.py + app/services/reporting.py).

Same two-phase, real-job-queue pattern as app/services/alerting.py and
app/services/retention.py: an API-triggered send (POST
/reports/subscription/send-now) enqueues via RQ so the request returns
immediately rather than blocking on PDF generation + an SMTP round trip;
the CRON-triggered path (scripts/run_scheduled_reports.py) calls
run_due_reports() directly and synchronously, since the script itself IS
already the explicit, out-of-band trigger — queueing it again would just
add indirection for something that isn't a request/response path in the
first place. Same split scripts/run_retention_purge.py already
established for the identical reason.

REPORT_DELIVERY_SYNC=1 (set by default in tests/conftest.py) runs the
queue in RQ's `is_async=False` mode — same meaning as ALERTING_SYNC /
RETENTION_SYNC: deterministic, in-process execution for tests, no real
worker process needed. The app's real default is async, requiring an
actual `rq worker scheduled_reports` process, same genuine new
operational requirement every other job-queue feature in this codebase
already carries.

`is_due()` is a simple "has enough calendar time passed since
last_sent_at" check, not a precise scheduler (no cron-expression parsing,
no timezone-of-recipient awareness) — a subscription with frequency
"weekly" is due once at least 7 days have passed since it was last sent
(or immediately, if it's never been sent). Good enough for this epic's
actual requirement ("deliver on a schedule"), not a general-purpose
scheduling engine.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from rq import Queue
from sqlalchemy import select

from app.core.db import get_session
from app.core.queue_client import queue_redis_client
from app.models.report_subscription import ReportSubscription
from app.models.user import User
from app.services.notifications import send_report_email
from app.services.reporting import build_analytics_pdf, build_audit_csv

logger = logging.getLogger("triage.reporting")

QUEUE_NAME = "scheduled_reports"

_FREQUENCY_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def get_subscription(user_id: int) -> ReportSubscription | None:
    with get_session() as session:
        sub = session.execute(
            select(ReportSubscription).where(ReportSubscription.user_id == user_id)
        ).scalar_one_or_none()
        if sub is not None:
            session.expunge(sub)
        return sub


def set_subscription(user_id: int, frequency: str, report_format: str) -> ReportSubscription:
    with get_session() as session:
        sub = session.execute(
            select(ReportSubscription).where(ReportSubscription.user_id == user_id)
        ).scalar_one_or_none()
        if sub is None:
            sub = ReportSubscription(user_id=user_id)
            session.add(sub)

        sub.frequency = frequency
        sub.report_format = report_format
        session.commit()
        session.refresh(sub)
        session.expunge(sub)
        return sub


def delete_subscription(user_id: int) -> bool:
    with get_session() as session:
        sub = session.execute(
            select(ReportSubscription).where(ReportSubscription.user_id == user_id)
        ).scalar_one_or_none()
        if sub is None:
            return False
        session.delete(sub)
        session.commit()
        return True


def _is_sync() -> bool:
    return os.environ.get("REPORT_DELIVERY_SYNC") == "1"


def get_report_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=queue_redis_client, is_async=not _is_sync())


def enqueue_report_send(subscription_id: int) -> None:
    get_report_queue().enqueue(send_one_report, subscription_id)


def is_due(subscription: ReportSubscription, now: datetime | None = None) -> bool:
    if subscription.last_sent_at is None:
        return True
    now = now or datetime.now(UTC)
    last_sent_at = subscription.last_sent_at
    if last_sent_at.tzinfo is None:
        # SQLite doesn't actually preserve tzinfo through DateTime(timezone=True)
        # (unlike Postgres) — every write in this codebase uses
        # datetime.now(UTC), so a naive value read back is always UTC.
        last_sent_at = last_sent_at.replace(tzinfo=UTC)
    window = timedelta(days=_FREQUENCY_DAYS.get(subscription.frequency, 7))
    return now - last_sent_at >= window


def send_one_report(subscription_id: int) -> bool:
    """The actual job body — must be a top-level, importable function
    (not a closure/lambda), since RQ resolves it by import path when a
    real worker process picks the job up from the queue. Always regenerates
    and sends regardless of is_due() — an explicit "send now" (API-
    triggered) or a cron run that already filtered to due subscriptions
    (run_due_reports()) both mean "send this one," not "check again."
    """
    with get_session() as session:
        subscription = session.get(ReportSubscription, subscription_id)
        if subscription is None:
            logger.warning("send_one_report: no such subscription %s", subscription_id)
            return False
        user = session.get(User, subscription.user_id)
        if user is None:
            logger.warning("send_one_report: no such user %s", subscription.user_id)
            return False
        user_id, org_id, frequency, report_format = (
            user.id,
            user.org_id,
            subscription.frequency,
            subscription.report_format,
        )

    days = _FREQUENCY_DAYS.get(frequency, 7)
    subject = f"Symptom Triage Assistant — {frequency} analytics report"
    message = (
        f"Attached is your {frequency} triage analytics report, covering the last "
        f"{days} day(s). This is an automated, informational summary — not a "
        "diagnostic or clinical judgment."
    )

    sent = False
    if report_format in ("csv", "both"):
        csv_bytes = build_audit_csv("org_admin", user_id, org_id, days)
        sent = send_report_email(
            user_id, subject, message, "triage_report.csv", csv_bytes, "text/csv"
        ) or sent
    if report_format in ("pdf", "both"):
        pdf_bytes = build_analytics_pdf("org_admin", user_id, org_id, days)
        sent = send_report_email(
            user_id, subject, message, "triage_report.pdf", pdf_bytes, "application/pdf"
        ) or sent

    # Only advance last_sent_at on at least partial delivery success —
    # unlike app/services/alerting.py's Alert.status (which stays "sent"
    # even if the notification itself fails, because the durable Alert
    # ROW is the artifact that must not be lost), a report has no
    # separate durable record of its own. Unconditionally bumping
    # last_sent_at on a failed send would make a persistent SMTP outage
    # invisible: the next scheduled run would see a "recently sent"
    # timestamp and skip, even though the org_admin never actually
    # received anything. Leaving it unset (or stale) instead means
    # run_due_reports() naturally retries on the next cron run.
    if sent:
        with get_session() as session:
            subscription = session.get(ReportSubscription, subscription_id)
            if subscription is not None:
                subscription.last_sent_at = datetime.now(UTC)
                session.commit()

    logger.info(
        "scheduled_report_sent",
        extra={"subscription_id": subscription_id, "user_id": user_id, "delivered": sent},
    )
    return sent


def run_due_reports() -> list[int]:
    """The cron entry point (scripts/run_scheduled_reports.py) — finds
    every subscription that's due and sends it synchronously, in-process.
    Returns the list of subscription ids that were sent, for the CLI's
    own reporting."""
    with get_session() as session:
        subscriptions = session.execute(select(ReportSubscription)).scalars().all()
        due_ids = [s.id for s in subscriptions if is_due(s)]

    sent_ids = []
    for subscription_id in due_ids:
        if send_one_report(subscription_id):
            sent_ids.append(subscription_id)
    return sent_ids
