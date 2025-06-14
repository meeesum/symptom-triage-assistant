"""Service-layer tests for app/services/report_delivery.py — subscription
CRUD, due-date logic, and the actual send job. Run with
REPORT_DELIVERY_SYNC=1 (set by default in tests/conftest.py), so
enqueue_report_send() executes send_one_report() inline — no real worker
process needed to assert on final state. See app/services/alerting.py's
test file for the identical pattern.
"""

from datetime import UTC, datetime, timedelta

from app.core.db import get_session
from app.models.report_subscription import ReportSubscription
from app.services.notifications import NotificationClient
from app.services.report_delivery import (
    delete_subscription,
    enqueue_report_send,
    get_subscription,
    is_due,
    run_due_reports,
    send_one_report,
    set_subscription,
)
from tests._auth_helpers import create_db_user


def _set_last_sent_at(subscription_id: int, when: datetime) -> None:
    with get_session() as session:
        sub = session.get(ReportSubscription, subscription_id)
        sub.last_sent_at = when
        session.commit()


def test_get_subscription_returns_none_when_unsubscribed():
    user_id = create_db_user("org_admin")
    assert get_subscription(user_id) is None


def test_set_subscription_creates_then_updates():
    user_id = create_db_user("org_admin")
    created = set_subscription(user_id, frequency="weekly", report_format="pdf")
    assert created.frequency == "weekly"
    assert created.report_format == "pdf"

    updated = set_subscription(user_id, frequency="daily", report_format="both")
    assert updated.id == created.id  # same row, not a duplicate
    assert updated.frequency == "daily"
    assert updated.report_format == "both"


def test_delete_subscription_removes_it():
    user_id = create_db_user("org_admin")
    set_subscription(user_id, frequency="weekly", report_format="csv")
    assert delete_subscription(user_id) is True
    assert get_subscription(user_id) is None


def test_delete_subscription_returns_false_when_none_exists():
    user_id = create_db_user("org_admin")
    assert delete_subscription(user_id) is False


def test_is_due_when_never_sent():
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="weekly", report_format="pdf")
    assert is_due(sub) is True


def test_is_due_false_when_recently_sent():
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="weekly", report_format="pdf")
    _set_last_sent_at(sub.id, datetime.now(UTC) - timedelta(days=1))
    sub = get_subscription(user_id)
    assert is_due(sub) is False


def test_is_due_true_once_frequency_window_has_passed():
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="daily", report_format="pdf")
    _set_last_sent_at(sub.id, datetime.now(UTC) - timedelta(days=2))
    sub = get_subscription(user_id)
    assert is_due(sub) is True


def test_send_one_report_updates_last_sent_at():
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="weekly", report_format="pdf")
    assert sub.last_sent_at is None

    result = send_one_report(sub.id)
    assert result is True  # ConsoleNotificationClient "succeeds" (logs, doesn't fail)

    updated = get_subscription(user_id)
    assert updated.last_sent_at is not None


def test_send_one_report_returns_false_for_unknown_subscription():
    assert send_one_report(999_999_999) is False


def test_enqueue_report_send_runs_synchronously_under_report_delivery_sync():
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="weekly", report_format="csv")
    enqueue_report_send(sub.id)
    updated = get_subscription(user_id)
    assert updated.last_sent_at is not None


class _AlwaysFailsEmailClient(NotificationClient):
    channel = "email"

    def send(self, recipient, subject, message):
        return False

    def send_with_attachment(self, recipient, subject, message, filename, content, content_type):
        return False


def test_last_sent_at_not_advanced_when_delivery_fails(monkeypatch):
    # A failed send must NOT bump last_sent_at — otherwise a persistent
    # SMTP outage would silently look like "already sent" forever, and
    # run_due_reports() would never retry. See report_delivery.py's
    # send_one_report() for the full reasoning.
    monkeypatch.setattr(
        "app.services.notifications.get_email_client", lambda: _AlwaysFailsEmailClient()
    )
    user_id = create_db_user("org_admin")
    sub = set_subscription(user_id, frequency="weekly", report_format="pdf")

    result = send_one_report(sub.id)

    assert result is False
    assert get_subscription(user_id).last_sent_at is None


def test_run_due_reports_only_sends_due_subscriptions():
    due_user = create_db_user("org_admin")
    due_sub = set_subscription(due_user, frequency="daily", report_format="pdf")
    _set_last_sent_at(due_sub.id, datetime.now(UTC) - timedelta(days=5))

    not_due_user = create_db_user("org_admin")
    not_due_sub = set_subscription(not_due_user, frequency="weekly", report_format="pdf")
    _set_last_sent_at(not_due_sub.id, datetime.now(UTC) - timedelta(hours=1))

    sent_ids = run_due_reports()

    assert due_sub.id in sent_ids
    assert not_due_sub.id not in sent_ids
