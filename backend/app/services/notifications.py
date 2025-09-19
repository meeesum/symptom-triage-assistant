"""Provider-agnostic email/SMS notification wrapper. Same pluggable
pattern as app/rag/llm_client.py's LLMClient: a deterministic, zero-setup
default (logs instead of sending) plus a real backend that only activates
when configured, so `pip install -r requirements.txt` and running the app
never requires real credentials.

Three implementations:

  - ConsoleNotificationClient (default for both channels): no network, no
    credentials — logs the notification structurally instead of sending
    it. Legitimate degraded-mode behavior too: a deployment that hasn't
    configured SMTP/Twilio yet still gets a record of what WOULD have
    been sent, in the logs, rather than a crash or a silent no-op.
  - SmtpEmailClient: a real email via Python's stdlib `smtplib` +
    `email.message` — deliberately no third-party email SDK, since SMTP
    needs nothing more than what the standard library already provides.
    Active when SMTP_HOST is set.
  - TwilioSmsClient: a real SMS via Twilio's REST API, called directly
    with stdlib `urllib.request` (HTTP Basic Auth + a form-encoded POST)
    rather than pulling in the `twilio` SDK for what is, at this call
    volume, a single API call — the same "don't add a dependency for
    what stdlib already covers" judgment as the email client. Active
    when TWILIO_ACCOUNT_SID is set.

get_email_client()/get_sms_client() resolve which implementation is
active per-channel independently — a deployment can have real email
without real SMS, or vice versa. notify_user() is the actual entry point
callers use (app/services/alerting.py's process_alert()): it reads the
user's NotificationPreference (defaulting to email-on/SMS-off for a user
who never set any) and dispatches through whichever clients are both
configured AND enabled for that user.
"""

from __future__ import annotations

import base64
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from email.message import EmailMessage

from sqlalchemy import select

from app.core.db import get_session
from app.models.notification_preference import NotificationPreference
from app.models.user import User

logger = logging.getLogger("triage.notifications")

_DEFAULT_EMAIL_ENABLED = True
_DEFAULT_SMS_ENABLED = False


class NotificationClient(ABC):
    channel: str

    @abstractmethod
    def send(self, recipient: str, subject: str, message: str) -> bool:
        """Returns True on success. Never raises — a failed notification
        must not be able to break the caller (see notify_user())."""

    def send_with_attachment(
        self,
        recipient: str,
        subject: str,
        message: str,
        attachment_filename: str,
        attachment_bytes: bytes,
        attachment_content_type: str,
    ) -> bool:
        """Default: ignore the attachment and send the plain message —
        correct for SMS (a file has no sane SMS representation) and the
        console fallback (there's no real transport to attach anything
        to). SmtpEmailClient overrides this to actually attach the file;
        see send_report_email() below, the one caller that needs this."""
        return self.send(recipient, subject, message)


class ConsoleNotificationClient(NotificationClient):
    def __init__(self, channel: str):
        self.channel = channel

    def send(self, recipient: str, subject: str, message: str) -> bool:
        logger.info(
            "notification_logged_not_sent",
            extra={"channel": self.channel, "recipient": recipient, "subject": subject},
        )
        return True


class SmtpEmailClient(NotificationClient):
    channel = "email"

    def __init__(self):
        self._host = os.environ["SMTP_HOST"]
        self._port = int(os.environ.get("SMTP_PORT", "587"))
        self._user = os.environ.get("SMTP_USER")
        self._password = os.environ.get("SMTP_PASSWORD")
        self._from_addr = os.environ.get("SMTP_FROM", self._user or "noreply@example.com")
        # Real relays on port 587 (Gmail, SendGrid, etc.) require STARTTLS —
        # true is the right default. But not every SMTP server supports
        # it (an internal relay on plain port 25, or a local dev/debug
        # server) — caught live while verifying this against a real local
        # SMTP server (aiosmtpd), which doesn't advertise STARTTLS at all
        # and made an unconditional smtp.starttls() call fail outright.
        self._use_tls = os.environ.get("SMTP_USE_TLS", "1") == "1"

    def send(self, recipient: str, subject: str, message: str) -> bool:
        import smtplib

        email_msg = EmailMessage()
        email_msg["Subject"] = subject
        email_msg["From"] = self._from_addr
        email_msg["To"] = recipient
        email_msg.set_content(message)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._user and self._password:
                    smtp.login(self._user, self._password)
                smtp.send_message(email_msg)
            return True
        except (OSError, smtplib.SMTPException):
            logger.exception("Failed to send email notification to %s", recipient)
            return False

    def send_with_attachment(
        self,
        recipient: str,
        subject: str,
        message: str,
        attachment_filename: str,
        attachment_bytes: bytes,
        attachment_content_type: str,
    ) -> bool:
        import smtplib

        maintype, _, subtype = attachment_content_type.partition("/")

        email_msg = EmailMessage()
        email_msg["Subject"] = subject
        email_msg["From"] = self._from_addr
        email_msg["To"] = recipient
        email_msg.set_content(message)
        email_msg.add_attachment(
            attachment_bytes,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment_filename,
        )

        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._user and self._password:
                    smtp.login(self._user, self._password)
                smtp.send_message(email_msg)
            return True
        except (OSError, smtplib.SMTPException):
            logger.exception("Failed to send email with attachment to %s", recipient)
            return False


class TwilioSmsClient(NotificationClient):
    channel = "sms"

    _API_URL_TEMPLATE = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

    def __init__(self):
        self._account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        self._auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        self._from_number = os.environ["TWILIO_FROM_NUMBER"]

    def send(self, recipient: str, subject: str, message: str) -> bool:
        url = self._API_URL_TEMPLATE.format(sid=self._account_sid)
        body = urllib.parse.urlencode(
            {"To": recipient, "From": self._from_number, "Body": f"{subject}: {message}"}
        ).encode()
        credentials = base64.b64encode(f"{self._account_sid}:{self._auth_token}".encode()).decode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, urllib.error.HTTPError):
            logger.exception("Failed to send SMS notification to %s", recipient)
            return False


def get_email_client() -> NotificationClient:
    if os.environ.get("SMTP_HOST"):
        return SmtpEmailClient()
    return ConsoleNotificationClient(channel="email")


def get_sms_client() -> NotificationClient:
    if os.environ.get("TWILIO_ACCOUNT_SID"):
        return TwilioSmsClient()
    return ConsoleNotificationClient(channel="sms")


def get_preferences(user_id: int) -> NotificationPreference | None:
    with get_session() as session:
        pref = session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).scalar_one_or_none()
        if pref is not None:
            session.expunge(pref)
        return pref


def set_preferences(
    user_id: int, email_enabled: bool, sms_enabled: bool, phone_number: str | None
) -> NotificationPreference:
    with get_session() as session:
        pref = session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=user_id)
            session.add(pref)

        pref.email_enabled = email_enabled
        pref.sms_enabled = sms_enabled
        pref.phone_number = phone_number
        session.commit()
        session.refresh(pref)
        session.expunge(pref)
        return pref


def notify_user(user_id: int, subject: str, message: str) -> dict[str, bool]:
    """Dispatches through whichever channels are enabled for this user
    (defaulting to email-on/SMS-off if they never set preferences).
    Never raises — see app/services/alerting.py's process_alert(), which
    calls this from an already-decoupled job; a notification failure here
    should be loud in logs, never able to crash the job.
    """
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            logger.warning("notify_user: no such user %s", user_id)
            return {}

        pref = session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).scalar_one_or_none()
        email_enabled = pref.email_enabled if pref else _DEFAULT_EMAIL_ENABLED
        sms_enabled = pref.sms_enabled if pref else _DEFAULT_SMS_ENABLED
        phone_number = pref.phone_number if pref else None
        email_address = user.email

    results: dict[str, bool] = {}

    if email_enabled:
        try:
            results["email"] = get_email_client().send(email_address, subject, message)
        except Exception:
            logger.exception("Unexpected error sending email notification to user %s", user_id)
            results["email"] = False

    if sms_enabled and phone_number:
        try:
            results["sms"] = get_sms_client().send(phone_number, subject, message)
        except Exception:
            logger.exception("Unexpected error sending SMS notification to user %s", user_id)
            results["sms"] = False

    return results


def send_report_email(
    user_id: int,
    subject: str,
    message: str,
    attachment_filename: str,
    attachment_bytes: bytes,
    attachment_content_type: str,
) -> bool:
    """Email-only (a scheduled analytics report has no sane SMS
    representation) — used by app/services/report_delivery.py. Ignores
    the recipient's email_enabled preference deliberately: a report is
    something the user explicitly subscribed to via
    app/api/reports.py's PUT /reports/subscription, a different, more
    specific opt-in than the general "notify me of high-risk alerts"
    preference notify_user() reads — unsubscribing from one shouldn't
    silently require also toggling the other off. Never raises, same
    contract as notify_user().
    """
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            logger.warning("send_report_email: no such user %s", user_id)
            return False
        email_address = user.email

    try:
        return get_email_client().send_with_attachment(
            email_address,
            subject,
            message,
            attachment_filename,
            attachment_bytes,
            attachment_content_type,
        )
    except Exception:
        logger.exception("Unexpected error sending report email to user %s", user_id)
        return False
