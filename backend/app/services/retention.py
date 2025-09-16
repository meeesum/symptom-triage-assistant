"""Retention & purge — configurable retention windows for chat history
and audit records, closing the gap named directly in the roadmap.

The roadmap also named "the revoked-token and refresh-token tables" as
part of this gap — that half is ALREADY closed, not by this epic:
docs/phase5b-redis-token-tracking.md moved both to self-expiring Redis
keys (a TTL, not a table), specifically so no purge job would ever be
needed for them. Worth saying explicitly rather than silently building a
purge job for tables that no longer exist, or re-implementing what
Redis's own TTL already does for free.

Uses the same job queue as app/services/alerting.py (RQ,
app/core/queue_client.py) — this is the "Retention & purge jobs" epic the
roadmap says depends on "High-risk alerting + job queue," and this is
that dependency actually being used. RETENTION_SYNC mirrors
ALERTING_SYNC: set to "1" by default in tests/conftest.py so a purge
enqueued in a test runs inline instead of needing a real worker process;
the app's real default is async, requiring an actual `rq worker
retention` process — same operational requirement `docs/phase7e-high-risk-alerting.md`
already established for alerts. scripts/run_retention_purge.py is the
realistic way a real deployment actually invokes this: as an explicit
cron entry, same "a migration/purge is a deploy step, not something the
app quietly does on its own" judgment as app/core/migrate.py.

Deletion, not anonymization, unlike app/services/data_rights.py's
"delete my data" — a RETENTION policy's whole point is that data
eventually goes away entirely once its window passes; a compliance
export/deletion REQUEST (Phase 8b) is about a specific individual's
rights right now, a different concern from an aged-out row nobody
requested anything about.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from rq import Queue
from sqlalchemy import delete, select

from app.core.db import get_session
from app.core.queue_client import queue_redis_client
from app.models.admin_action_log import AdminActionLog
from app.models.audit import TriageAuditRecord
from app.models.chat_exchange import ChatExchange
from app.models.retention_purge_run import RetentionPurgeRun
from app.services.symptom_photos import delete_photos_for_audit_record

QUEUE_NAME = "retention_purge"

DEFAULT_CHAT_HISTORY_RETENTION_DAYS = 90
DEFAULT_AUDIT_RECORD_RETENTION_DAYS = 365
DEFAULT_ADMIN_ACTION_LOG_RETENTION_DAYS = 365


def _retention_days(env_var: str, default: int) -> int:
    return int(os.environ.get(env_var, default))


def _is_sync() -> bool:
    return os.environ.get("RETENTION_SYNC") == "1"


def get_retention_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=queue_redis_client, is_async=not _is_sync())


def enqueue_retention_purge() -> None:
    get_retention_queue().enqueue(purge_old_data)


def purge_old_data() -> RetentionPurgeRun:
    """The job body — must be a top-level, importable function (not a
    closure/lambda), since RQ resolves it by import path when a real
    worker picks the job up. Also the function scripts/run_retention_purge.py
    calls directly for a synchronous, cron-triggered run."""
    now = datetime.now(UTC)
    chat_cutoff = now - timedelta(
        days=_retention_days("CHAT_HISTORY_RETENTION_DAYS", DEFAULT_CHAT_HISTORY_RETENTION_DAYS)
    )
    audit_cutoff = now - timedelta(
        days=_retention_days("AUDIT_RECORD_RETENTION_DAYS", DEFAULT_AUDIT_RECORD_RETENTION_DAYS)
    )
    action_log_cutoff = now - timedelta(
        days=_retention_days(
            "ADMIN_ACTION_LOG_RETENTION_DAYS", DEFAULT_ADMIN_ACTION_LOG_RETENTION_DAYS
        )
    )

    # Photos are deleted BEFORE the audit records they're attached to —
    # audit_record_id is a plain Integer, not a SQLAlchemy ForeignKey
    # (same pattern as every other cross-table reference in this
    # codebase), so nothing would raise an error if this were skipped;
    # the photo rows and their on-disk files would just silently
    # outlive the record they document. Done in its OWN, separate
    # session/query — deliberately not inside the main transaction
    # below — because delete_photos_for_audit_record() opens (and
    # commits) its own session per photo via delete_photo(), which
    # can't safely nest inside another still-open session/transaction
    # (SQLite in particular only allows one writer at a time; a nested
    # commit here could deadlock against the outer, not-yet-committed
    # transaction).
    with get_session() as session:
        expiring_ids = session.execute(
            select(TriageAuditRecord.id).where(TriageAuditRecord.created_at < audit_cutoff)
        ).scalars().all()
    photos_deleted = sum(delete_photos_for_audit_record(rid) for rid in expiring_ids)

    with get_session() as session:
        chat_result = session.execute(
            delete(ChatExchange).where(ChatExchange.created_at < chat_cutoff)
        )
        audit_result = session.execute(
            delete(TriageAuditRecord).where(TriageAuditRecord.created_at < audit_cutoff)
        )
        action_log_result = session.execute(
            delete(AdminActionLog).where(AdminActionLog.created_at < action_log_cutoff)
        )

        run = RetentionPurgeRun(
            chat_exchanges_deleted=chat_result.rowcount,
            audit_records_deleted=audit_result.rowcount,
            admin_action_logs_deleted=action_log_result.rowcount,
            symptom_photos_deleted=photos_deleted,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        session.expunge(run)
        return run


def list_purge_runs(limit: int = 50) -> list[RetentionPurgeRun]:
    with get_session() as session:
        rows = (
            session.execute(
                select(RetentionPurgeRun).order_by(RetentionPurgeRun.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows
