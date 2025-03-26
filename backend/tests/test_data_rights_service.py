import pytest

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.models.chat_exchange import ChatExchange
from app.models.notification_preference import NotificationPreference
from app.models.user import User
from app.services.consent import record_consent
from app.services.data_rights import UserNotFound, delete_user_data, export_user_data, list_data_requests
from app.services.notifications import set_preferences
from app.services.refresh_tokens import issue_refresh_token, rotate_refresh_token
from tests._auth_helpers import create_db_user


def _create_chat_exchange(user_id: int) -> int:
    with get_session() as session:
        chat = ChatExchange(
            user_id=user_id,
            user_text="I have a cough",
            tier="self_care",
            guidance="rest and fluids",
        )
        session.add(chat)
        session.commit()
        session.refresh(chat)
        return chat.id


def _create_audit_record(patient_id: int) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["cough"],
            severity="mild",
            onset="gradual",
            tier="self_care",
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_export_unknown_user_raises():
    with pytest.raises(UserNotFound):
        export_user_data(999999)


def test_export_includes_account_chat_and_audit_data():
    user_id = create_db_user("patient")
    _create_chat_exchange(user_id)
    _create_audit_record(user_id)
    record_consent(user_id, "data_processing", granted=True)

    export = export_user_data(user_id)
    assert export["account"]["id"] == user_id
    assert len(export["chat_history"]) == 1
    assert len(export["audit_records"]) == 1
    assert len(export["consent_history"]) == 1


def test_export_creates_a_data_request_record():
    user_id = create_db_user("patient")
    export_user_data(user_id)
    requests = list_data_requests(user_id)
    assert len(requests) == 1
    assert requests[0].request_type == "export"
    assert requests[0].status == "completed"


def test_deletion_unknown_user_raises():
    with pytest.raises(UserNotFound):
        delete_user_data(999999)


def test_deletion_deletes_chat_history():
    user_id = create_db_user("patient")
    _create_chat_exchange(user_id)
    delete_user_data(user_id)

    with get_session() as session:
        remaining = session.query(ChatExchange).filter(ChatExchange.user_id == user_id).all()
        assert remaining == []


def test_deletion_unlinks_but_keeps_audit_records():
    user_id = create_db_user("patient")
    record_id = _create_audit_record(user_id)
    delete_user_data(user_id)

    with get_session() as session:
        record = session.get(TriageAuditRecord, record_id)
        assert record is not None  # still exists
        assert record.patient_id is None  # unlinked


def test_deletion_removes_notification_preferences():
    user_id = create_db_user("patient")
    set_preferences(user_id, email_enabled=True, sms_enabled=True, phone_number="+15551234567")
    delete_user_data(user_id)

    with get_session() as session:
        pref = (
            session.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .one_or_none()
        )
        assert pref is None


def test_deletion_anonymizes_account_and_prevents_login():
    user_id = create_db_user("patient")
    with get_session() as session:
        original_email = session.get(User, user_id).email

    delete_user_data(user_id)

    with get_session() as session:
        user = session.get(User, user_id)
        assert user.email != original_email
        assert "deleted" in user.email


def test_deletion_revokes_existing_refresh_tokens():
    user_id = create_db_user("patient")
    refresh_token = issue_refresh_token(user_id)
    delete_user_data(user_id)

    from app.services.refresh_tokens import RefreshTokenInvalid

    with pytest.raises(RefreshTokenInvalid):
        rotate_refresh_token(refresh_token)


def test_deletion_creates_a_data_request_record():
    user_id = create_db_user("patient")
    delete_user_data(user_id)
    requests = list_data_requests(user_id)
    assert len(requests) == 1
    assert requests[0].request_type == "deletion"
    assert requests[0].status == "completed"


def test_list_data_requests_scoped_to_that_user_only():
    user_a = create_db_user("patient")
    user_b = create_db_user("patient")
    export_user_data(user_a)
    assert len(list_data_requests(user_a)) == 1
    assert list_data_requests(user_b) == []
