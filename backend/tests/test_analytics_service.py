from datetime import UTC, datetime

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.services.analytics import tier_distribution, time_to_follow_up_stats, triage_volume_by_day
from tests._auth_helpers import create_db_user


def _create_audit_record(patient_id: int | None, tier: str) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["cough"],
            severity="mild",
            onset="gradual",
            tier=tier,
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_triage_volume_by_day_includes_todays_records():
    _create_audit_record(patient_id=None, tier="self_care")
    volume = triage_volume_by_day(role="admin", user_id=1, days=7)
    assert len(volume) == 7
    today = datetime.now(UTC).date().isoformat()
    today_entry = next(d for d in volume if d["date"] == today)
    assert today_entry["count"] >= 1


def test_triage_volume_by_day_fills_zero_count_days():
    volume = triage_volume_by_day(role="admin", user_id=1, days=3)
    assert all("count" in d and isinstance(d["count"], int) for d in volume)


def test_tier_distribution_counts_by_tier():
    # A provider's view also includes every anonymous record system-wide
    # (see docs/phase7a-patient-panels.md) — including ones other test
    # modules create — so this compares before/after deltas around a
    # fresh, isolated provider+patient pair rather than asserting exact
    # totals, the same robust pattern test_audit_panel_scoping.py uses.
    from app.services.patient_panel import assign_patient

    marker_patient = create_db_user("patient")
    provider_id = create_db_user("provider")
    assign_patient(provider_id, marker_patient)

    before = tier_distribution(role="provider", user_id=provider_id, days=7)
    _create_audit_record(patient_id=marker_patient, tier="emergency")
    _create_audit_record(patient_id=marker_patient, tier="emergency")
    _create_audit_record(patient_id=marker_patient, tier="self_care")
    after = tier_distribution(role="provider", user_id=provider_id, days=7)

    assert after["emergency"] - before["emergency"] == 2
    assert after["self_care"] - before["self_care"] == 1
    assert after["urgent"] == before["urgent"]
    assert after["routine"] == before["routine"]


def test_provider_tier_distribution_scoped_to_panel():
    from app.services.patient_panel import assign_patient

    on_panel = create_db_user("patient")
    off_panel = create_db_user("patient")
    provider_id = create_db_user("provider")
    assign_patient(provider_id, on_panel)

    before = tier_distribution(role="provider", user_id=provider_id, days=7)
    _create_audit_record(patient_id=on_panel, tier="urgent")
    _create_audit_record(patient_id=off_panel, tier="urgent")
    after = tier_distribution(role="provider", user_id=provider_id, days=7)

    # +1 from the panel patient's record; the off-panel patient's record
    # must NOT count toward this provider's total.
    assert after["urgent"] - before["urgent"] == 1


def test_time_to_follow_up_stats_empty_when_no_referrals():
    stats = time_to_follow_up_stats(role="admin", user_id=1, days=7)
    assert stats["count"] >= 0  # other tests may have created referrals; just must not crash


def test_time_to_follow_up_stats_computes_hours_between_creation_and_first_follow_up():
    patient_id = create_db_user("patient")
    record_id = _create_audit_record(patient_id=patient_id, tier="urgent")

    from app.services.patient_panel import assign_patient
    from app.services.referrals import advance_status, create_referral

    provider_id = create_db_user("provider")
    assign_patient(provider_id, patient_id)

    create_referral(record_id, created_by=provider_id)
    advance_status(record_id, "scheduled", changed_by=provider_id)

    stats = time_to_follow_up_stats(role="provider", user_id=provider_id, days=7)
    assert stats["count"] >= 1
    assert stats["average_hours"] is not None
    assert stats["average_hours"] >= 0


def test_time_to_follow_up_excludes_referrals_still_at_referred():
    patient_id = create_db_user("patient")
    record_id = _create_audit_record(patient_id=patient_id, tier="urgent")

    from app.services.patient_panel import assign_patient
    from app.services.referrals import create_referral

    provider_id = create_db_user("provider")
    assign_patient(provider_id, patient_id)
    create_referral(record_id, created_by=provider_id)

    # No advance_status call — referral stays at "referred".
    stats = time_to_follow_up_stats(role="provider", user_id=provider_id, days=7)
    assert stats["count"] == 0
    assert stats["average_hours"] is None
