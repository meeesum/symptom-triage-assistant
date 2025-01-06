"""RETENTION_SYNC=1 (set by default in tests/conftest.py) makes
enqueue_retention_purge() execute purge_old_data() inline — see
app/services/retention.py.
"""

from datetime import UTC, datetime, timedelta

from app.core.db import get_session
from app.models.admin_action_log import AdminActionLog
from app.models.audit import TriageAuditRecord
from app.models.chat_exchange import ChatExchange
from app.services.retention import list_purge_runs, purge_old_data


def _create_chat_exchange(created_at: datetime | None = None) -> int:
    with get_session() as session:
        chat = ChatExchange(
            user_id=1, user_text="test", tier="self_care", guidance="rest"
        )
        session.add(chat)
        session.flush()
        if created_at is not None:
            chat.created_at = created_at
        session.commit()
        session.refresh(chat)
        return chat.id


def _create_audit_record(created_at: datetime | None = None) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            symptom_ids=["cough"],
            severity="mild",
            onset="gradual",
            tier="self_care",
            decision_source="test",
        )
        session.add(record)
        session.flush()
        if created_at is not None:
            record.created_at = created_at
        session.commit()
        session.refresh(record)
        return record.id


def _create_action_log(created_at: datetime | None = None) -> int:
    with get_session() as session:
        entry = AdminActionLog(
            actor_id=1, actor_role="admin", actor_org_id=1,
            action="test_action", target_type="test",
        )
        session.add(entry)
        session.flush()
        if created_at is not None:
            entry.created_at = created_at
        session.commit()
        session.refresh(entry)
        return entry.id


def test_purge_deletes_chat_exchanges_older_than_retention_window(monkeypatch):
    monkeypatch.setenv("CHAT_HISTORY_RETENTION_DAYS", "90")
    old_id = _create_chat_exchange(created_at=datetime.now(UTC) - timedelta(days=100))
    recent_id = _create_chat_exchange(created_at=datetime.now(UTC) - timedelta(days=1))

    purge_old_data()

    with get_session() as session:
        assert session.get(ChatExchange, old_id) is None
        assert session.get(ChatExchange, recent_id) is not None


def test_purge_deletes_audit_records_older_than_retention_window(monkeypatch):
    monkeypatch.setenv("AUDIT_RECORD_RETENTION_DAYS", "365")
    old_id = _create_audit_record(created_at=datetime.now(UTC) - timedelta(days=400))
    recent_id = _create_audit_record(created_at=datetime.now(UTC) - timedelta(days=1))

    purge_old_data()

    with get_session() as session:
        assert session.get(TriageAuditRecord, old_id) is None
        assert session.get(TriageAuditRecord, recent_id) is not None


def test_purge_deletes_admin_action_logs_older_than_retention_window(monkeypatch):
    monkeypatch.setenv("ADMIN_ACTION_LOG_RETENTION_DAYS", "365")
    old_id = _create_action_log(created_at=datetime.now(UTC) - timedelta(days=400))
    recent_id = _create_action_log(created_at=datetime.now(UTC) - timedelta(days=1))

    purge_old_data()

    with get_session() as session:
        assert session.get(AdminActionLog, old_id) is None
        assert session.get(AdminActionLog, recent_id) is not None


def test_purge_run_is_recorded_with_correct_counts(monkeypatch):
    monkeypatch.setenv("CHAT_HISTORY_RETENTION_DAYS", "90")
    _create_chat_exchange(created_at=datetime.now(UTC) - timedelta(days=200))
    _create_chat_exchange(created_at=datetime.now(UTC) - timedelta(days=200))

    run = purge_old_data()
    assert run.chat_exchanges_deleted >= 2

    runs = list_purge_runs(limit=1)
    assert runs[0].id == run.id


def test_purge_respects_custom_retention_window(monkeypatch):
    # A very short window should purge something created "recently" too.
    monkeypatch.setenv("CHAT_HISTORY_RETENTION_DAYS", "0")
    old_id = _create_chat_exchange(created_at=datetime.now(UTC) - timedelta(hours=1))

    purge_old_data()

    with get_session() as session:
        assert session.get(ChatExchange, old_id) is None
