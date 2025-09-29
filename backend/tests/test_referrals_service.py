import pytest

from app.services.referrals import (
    InvalidStatusTransition,
    ReferralAlreadyExists,
    ReferralNotFound,
    advance_status,
    create_referral,
    get_referral,
    get_status_history,
)

_record_id_counter = 10_000


def _next_record_id() -> int:
    global _record_id_counter
    _record_id_counter += 1
    return _record_id_counter


def test_create_referral_starts_at_referred():
    record_id = _next_record_id()
    referral = create_referral(record_id, created_by=1)
    assert referral.status == "referred"
    assert referral.audit_record_id == record_id


def test_create_referral_records_initial_history_entry():
    record_id = _next_record_id()
    referral = create_referral(record_id, created_by=1)
    history = get_status_history(referral.id)
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == "referred"


def test_duplicate_referral_for_same_record_raises():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    with pytest.raises(ReferralAlreadyExists):
        create_referral(record_id, created_by=1)


def test_get_referral_returns_none_when_absent():
    assert get_referral(_next_record_id()) is None


def test_advance_status_forward():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    referral = advance_status(record_id, "scheduled", changed_by=2)
    assert referral.status == "scheduled"


def test_advance_status_can_skip_a_stage():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    referral = advance_status(record_id, "seen", changed_by=2)
    assert referral.status == "seen"


def test_advance_status_rejects_backward_move():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    advance_status(record_id, "seen", changed_by=2)
    with pytest.raises(InvalidStatusTransition):
        advance_status(record_id, "scheduled", changed_by=2)


def test_advance_status_rejects_same_status():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    with pytest.raises(InvalidStatusTransition):
        advance_status(record_id, "referred", changed_by=2)


def test_advance_status_rejects_unknown_status():
    record_id = _next_record_id()
    create_referral(record_id, created_by=1)
    with pytest.raises(InvalidStatusTransition):
        advance_status(record_id, "bogus", changed_by=2)


def test_advance_status_on_unknown_referral_raises_not_found():
    with pytest.raises(ReferralNotFound):
        advance_status(_next_record_id(), "scheduled", changed_by=2)


def test_status_history_accumulates_across_transitions():
    record_id = _next_record_id()
    referral = create_referral(record_id, created_by=1)
    advance_status(record_id, "scheduled", changed_by=2)
    advance_status(record_id, "seen", changed_by=3)

    history = get_status_history(referral.id)
    assert [h.to_status for h in history] == ["referred", "scheduled", "seen"]
    assert [h.changed_by for h in history] == [1, 2, 3]
