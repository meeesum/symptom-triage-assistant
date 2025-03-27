"""Tests run with ALERTING_SYNC=1 (set by default in tests/conftest.py) —
enqueue() executes process_alert() inline, so these can assert on the
final state without a real worker process. See app/services/alerting.py.
"""

from app.core.db import get_session
from app.models.alert import Alert
from app.models.audit import TriageAuditRecord
from app.services.alerting import trigger_high_risk_alert
from app.services.patient_panel import assign_patient
from tests._auth_helpers import create_db_user

_record_id_counter = 30_000


def _next_id() -> int:
    global _record_id_counter
    _record_id_counter += 1
    return _record_id_counter


def _create_audit_record(patient_id: int | None) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["chest_pain"],
            severity="severe",
            onset="sudden",
            tier="emergency",
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_trigger_creates_a_queued_then_sent_alert():
    record_id = _create_audit_record(patient_id=None)
    alert = trigger_high_risk_alert(record_id, message="Call 911 now.")
    assert alert is not None

    with get_session() as session:
        row = session.get(Alert, alert.id)
        # Synchronous mode means process_alert() already ran by the time
        # trigger_high_risk_alert() returns.
        assert row.status == "sent"
        assert row.sent_at is not None
        assert row.message == "Call 911 now."


def test_trigger_resolves_recipient_from_patient_panel():
    patient_id = create_db_user("patient")
    provider_id = create_db_user("provider")
    assign_patient(provider_id, patient_id)

    record_id = _create_audit_record(patient_id=patient_id)
    alert = trigger_high_risk_alert(record_id, message="Emergency case.")

    with get_session() as session:
        row = session.get(Alert, alert.id)
        assert row.recipient_provider_id == provider_id


def test_trigger_leaves_recipient_none_for_anonymous_record():
    record_id = _create_audit_record(patient_id=None)
    alert = trigger_high_risk_alert(record_id, message="Emergency case.")

    with get_session() as session:
        row = session.get(Alert, alert.id)
        assert row.recipient_provider_id is None
        assert row.status == "sent"  # still processed — just no specific recipient


def test_trigger_leaves_recipient_none_for_patient_with_no_panel():
    patient_id = _next_id()  # never assigned to any provider
    record_id = _create_audit_record(patient_id=patient_id)
    alert = trigger_high_risk_alert(record_id, message="Emergency case.")

    with get_session() as session:
        row = session.get(Alert, alert.id)
        assert row.recipient_provider_id is None


def test_trigger_links_alert_to_the_right_audit_record():
    record_id = _create_audit_record(patient_id=None)
    alert = trigger_high_risk_alert(record_id, message="msg")
    assert alert.audit_record_id == record_id
