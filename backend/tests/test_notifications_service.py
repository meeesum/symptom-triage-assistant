"""No real SMTP/Twilio credentials are configured in this dev
environment (see conftest.py — nothing sets SMTP_HOST/TWILIO_ACCOUNT_SID),
so get_email_client()/get_sms_client() resolve to ConsoleNotificationClient
by default here, same "zero-setup default" pattern as the rest of this
codebase's pluggable clients. Real-backend wiring is verified with fakes
(mirroring test_rag_pipeline.py's _FakeAnthropicClient pattern), not a
live SMTP/Twilio call.
"""

from app.core.db import get_session
from app.core.security import hash_password
from app.models.user import User
from app.services.organizations import DEFAULT_ORG_SLUG, get_org_by_slug
from app.services.notifications import (
    ConsoleNotificationClient,
    NotificationClient,
    get_email_client,
    get_preferences,
    get_sms_client,
    notify_user,
    set_preferences,
)

_email_counter = 0


def _create_user(role: str = "provider") -> int:
    global _email_counter
    _email_counter += 1
    with get_session() as session:
        default_org = get_org_by_slug(DEFAULT_ORG_SLUG)
        user = User(
            email=f"notify-test-{_email_counter}@example.com",
            hashed_password=hash_password("correct-horse-battery-staple"),
            role=role,
            org_id=default_org.id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


class _FakeClient(NotificationClient):
    def __init__(self, channel: str, succeeds: bool = True):
        self.channel = channel
        self._succeeds = succeeds
        self.sent = []

    def send(self, recipient: str, subject: str, message: str) -> bool:
        self.sent.append((recipient, subject, message))
        return self._succeeds


def test_get_email_client_defaults_to_console_without_smtp_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    client = get_email_client()
    assert isinstance(client, ConsoleNotificationClient)
    assert client.channel == "email"


def test_get_sms_client_defaults_to_console_without_twilio_configured(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    client = get_sms_client()
    assert isinstance(client, ConsoleNotificationClient)
    assert client.channel == "sms"


def test_console_client_send_always_succeeds():
    client = ConsoleNotificationClient(channel="email")
    assert client.send("a@example.com", "subject", "message") is True


def test_get_preferences_returns_none_when_unset():
    user_id = _create_user()
    assert get_preferences(user_id) is None


def test_set_preferences_creates_and_get_returns_it():
    user_id = _create_user()
    set_preferences(user_id, email_enabled=False, sms_enabled=True, phone_number="+15551234567")

    pref = get_preferences(user_id)
    assert pref is not None
    assert pref.email_enabled is False
    assert pref.sms_enabled is True
    assert pref.phone_number == "+15551234567"


def test_set_preferences_is_idempotent_upsert():
    user_id = _create_user()
    set_preferences(user_id, email_enabled=True, sms_enabled=False, phone_number=None)
    set_preferences(user_id, email_enabled=False, sms_enabled=True, phone_number="+15559876543")

    pref = get_preferences(user_id)
    assert pref.email_enabled is False
    assert pref.sms_enabled is True
    assert pref.phone_number == "+15559876543"


def test_notify_user_defaults_to_email_only_with_no_preferences_set(monkeypatch):
    user_id = _create_user()
    fake_email = _FakeClient("email")
    monkeypatch.setattr("app.services.notifications.get_email_client", lambda: fake_email)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {"email": True}
    assert len(fake_email.sent) == 1


def test_notify_user_respects_disabled_email(monkeypatch):
    user_id = _create_user()
    set_preferences(user_id, email_enabled=False, sms_enabled=False, phone_number=None)
    fake_email = _FakeClient("email")
    monkeypatch.setattr("app.services.notifications.get_email_client", lambda: fake_email)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {}
    assert fake_email.sent == []


def test_notify_user_sends_sms_when_enabled_with_phone_number(monkeypatch):
    user_id = _create_user()
    set_preferences(
        user_id, email_enabled=False, sms_enabled=True, phone_number="+15551234567"
    )
    fake_sms = _FakeClient("sms")
    monkeypatch.setattr("app.services.notifications.get_sms_client", lambda: fake_sms)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {"sms": True}
    assert fake_sms.sent == [("+15551234567", "Test", "body")]


def test_notify_user_skips_sms_when_enabled_but_no_phone_number(monkeypatch):
    user_id = _create_user()
    set_preferences(user_id, email_enabled=False, sms_enabled=True, phone_number=None)
    fake_sms = _FakeClient("sms")
    monkeypatch.setattr("app.services.notifications.get_sms_client", lambda: fake_sms)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {}
    assert fake_sms.sent == []


def test_notify_user_can_dispatch_both_channels(monkeypatch):
    user_id = _create_user()
    set_preferences(user_id, email_enabled=True, sms_enabled=True, phone_number="+15551234567")
    fake_email = _FakeClient("email")
    fake_sms = _FakeClient("sms")
    monkeypatch.setattr("app.services.notifications.get_email_client", lambda: fake_email)
    monkeypatch.setattr("app.services.notifications.get_sms_client", lambda: fake_sms)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {"email": True, "sms": True}


def test_notify_user_records_failure_without_raising(monkeypatch):
    user_id = _create_user()
    fake_email = _FakeClient("email", succeeds=False)
    monkeypatch.setattr("app.services.notifications.get_email_client", lambda: fake_email)

    results = notify_user(user_id, subject="Test", message="body")
    assert results == {"email": False}


def test_notify_user_unknown_user_returns_empty():
    assert notify_user(999999, subject="Test", message="body") == {}
