"""GDPR/HIPAA-style data export and deletion (erasure) requests. See
app/models/data_request.py and docs/phase8b-consent-and-data-rights.md.

Export and deletion are both synchronous (not queued, unlike
app/services/alerting.py's high-risk alerts) — the roadmap epic that
depends on the job queue is "Retention & purge jobs," a later epic, not
this one. A single user's own data is small and bounded (their own chat
history + audit rows), so there's no latency reason to defer this work.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select

from app.core.db import get_session
from app.core.security import hash_password
from app.models.audit import TriageAuditRecord
from app.models.chat_exchange import ChatExchange
from app.models.consent import ConsentRecord
from app.models.data_request import DataRequest
from app.models.notification_preference import NotificationPreference
from app.models.user import User
from app.services.refresh_tokens import revoke_all_refresh_tokens_for_user
from app.services.symptom_photos import delete_photo, list_photos_for_patient


class UserNotFound(Exception):
    pass


def _record_request(user_id: int, request_type: str, status: str, summary: str) -> DataRequest:
    with get_session() as session:
        request = DataRequest(
            user_id=user_id, request_type=request_type, status=status, summary=summary
        )
        session.add(request)
        session.commit()
        session.refresh(request)
        session.expunge(request)
        return request


def list_data_requests(user_id: int) -> list[DataRequest]:
    with get_session() as session:
        rows = (
            session.execute(
                select(DataRequest).where(DataRequest.user_id == user_id).order_by(DataRequest.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def export_user_data(user_id: int) -> dict:
    """Everything this product actually stores that's tied to this user:
    account info, consent history, chat history (uncapped — GET
    /triage/history caps at 200 for normal browsing, an export can't
    silently truncate), and every audit record attributable to them.
    Deliberately does NOT include clinical notes or referrals a PROVIDER
    wrote on OTHER patients' records — this export is about data
    belonging to the requesting user, not their work product about
    someone else. See docs/phase8b-consent-and-data-rights.md for what's
    still out of scope (e.g. a patient's right to see notes ABOUT them,
    written by a provider)."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise UserNotFound(f"no such user: {user_id}")

        chats = session.execute(
            select(ChatExchange).where(ChatExchange.user_id == user_id).order_by(ChatExchange.id)
        ).scalars().all()
        audit_records = session.execute(
            select(TriageAuditRecord)
            .where(TriageAuditRecord.patient_id == user_id)
            .order_by(TriageAuditRecord.id)
        ).scalars().all()
        consents = session.execute(
            select(ConsentRecord).where(ConsentRecord.user_id == user_id).order_by(ConsentRecord.id)
        ).scalars().all()

        export = {
            "account": {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "org_id": user.org_id,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "consent_history": [
                {
                    "consent_type": c.consent_type,
                    "granted": c.granted,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in consents
            ],
            "chat_history": [
                {
                    "id": c.id,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "user_text": c.user_text,
                    "tier": c.tier,
                    "guidance": c.guidance,
                    "understood_symptom_ids": c.understood_symptom_ids,
                }
                for c in chats
            ],
            "audit_records": [
                {
                    "id": a.id,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "symptom_ids": a.symptom_ids,
                    "severity": a.severity,
                    "tier": a.tier,
                    "free_text_excerpt": a.free_text_excerpt,
                }
                for a in audit_records
            ],
        }

    _record_request(
        user_id,
        "export",
        "completed",
        f"{len(chats)} chat exchange(s), {len(audit_records)} audit record(s)",
    )
    return export


def delete_user_data(user_id: int) -> DataRequest:
    """Deletion here means anonymization, not a hard DELETE of the User
    row — a deliberate choice, not a shortcut:

      - The account is scrambled to an unrecoverable, unguessable email
        and an unusable random password hash (login becomes permanently
        impossible) rather than deleted outright, because dozens of
        OTHER tables in this codebase reference a user's id with a plain
        Integer, not a SQLAlchemy ForeignKey (PatientPanelAssignment,
        ClinicalNote.author_id, Referral.created_by, KbArticleSubmission
        .submitted_by, and more — see app/models/patient_panel.py's
        docstring for why that pattern exists throughout). Deleting the
        row would silently orphan every one of those references, with no
        constraint to even catch it, and would destroy the ability to
        ever answer "who approved this KB article" or "who wrote this
        clinical note" for a real compliance review — the opposite of
        what a compliance epic should do.
      - Their own chat history (ChatExchange rows) IS actually deleted —
        this is patient-authored free text about themselves, exactly
        what "delete my chat history" (named directly in
        docs/phase4c-chat-history.md's own open items) means.
      - Their uploaded symptom photos (SymptomPhoto rows AND the actual
        files on disk — see app/services/symptom_photos.py's
        delete_photo()) are actually deleted, same category as chat
        history: patient-submitted content about themselves, and
        frequently more sensitive than the free text (an actual photo of
        a rash, injury, or other symptom). This was a real gap found and
        closed by the Phase 06 cross-phase contract-tests epic: symptom
        photo upload (Phase 05) was built after this data-rights epic
        (Phase 04) and was never wired back into it — a "delete my data"
        request left every uploaded photo fully intact on disk and in
        the DB, indefinitely. See
        docs/phase10c-cross-phase-contract-tests.md.
      - Their audit records are NOT deleted, but unlinked:
        `patient_id` is set to NULL, same as an anonymous triage request
        — the clinical/compliance record of what happened stays intact
        (required for the audit trail's own purpose), but it can no
        longer be tied back to this specific person.
      - Their notification preferences are deleted outright — nothing
        to anonymize, just a preference no one needs anymore for an
        account that can't log in.
      - Every refresh token they've ever issued is revoked immediately —
        an anonymized account whose old password no longer works would
        otherwise still be usable for up to 7 more days via a refresh
        token minted before the request.

    This is the "anonymize, don't hard-delete" pattern GDPR's own erasure
    provisions explicitly allow when a legitimate reason to retain
    de-identified records exists (Art. 17(3) — here, the audit trail's
    own compliance purpose) — not a workaround, a recognized approach.
    """
    with get_session() as session:
        if session.get(User, user_id) is None:
            raise UserNotFound(f"no such user: {user_id}")

    # Deleted via its own service (which also removes the on-disk file —
    # see delete_photo()'s docstring), before the main anonymization
    # transaction below rather than inside it: delete_photo() opens its
    # own session per photo, which can't safely nest inside another
    # open session/transaction.
    photos = list_photos_for_patient(user_id)
    for photo in photos:
        delete_photo(photo)

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise UserNotFound(f"no such user: {user_id}")

        chat_count = session.execute(
            select(ChatExchange).where(ChatExchange.user_id == user_id)
        ).scalars().all()
        for chat in chat_count:
            session.delete(chat)

        audit_records = session.execute(
            select(TriageAuditRecord).where(TriageAuditRecord.patient_id == user_id)
        ).scalars().all()
        for record in audit_records:
            record.patient_id = None

        pref = session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).scalar_one_or_none()
        if pref is not None:
            session.delete(pref)

        user.email = f"deleted-user-{user.id}-{secrets.token_hex(8)}@deleted.invalid"
        user.hashed_password = hash_password(secrets.token_urlsafe(32))
        session.commit()

    # An anonymized account must not stay usable via an already-issued
    # refresh token for the rest of its 7-day life — see
    # app/services/refresh_tokens.py. The CURRENT access token is a
    # separate concern handled by the API layer (app/api/data_rights.py),
    # which has the request's own jti; this service only knows the
    # user_id.
    revoke_all_refresh_tokens_for_user(user_id)

    return _record_request(
        user_id,
        "deletion",
        "completed",
        f"{len(photos)} symptom photo(s) deleted, {len(chat_count)} chat exchange(s) deleted, "
        f"{len(audit_records)} audit "
        "record(s) unlinked, account anonymized",
    )
