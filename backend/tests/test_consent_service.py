from app.services.consent import get_consent_history, get_current_consent, has_consented, record_consent
from tests._auth_helpers import create_db_user


def test_has_consented_false_when_never_recorded():
    user_id = create_db_user("patient")
    assert has_consented(user_id, "data_processing") is False


def test_record_consent_then_has_consented_true():
    user_id = create_db_user("patient")
    record_consent(user_id, "data_processing", granted=True)
    assert has_consented(user_id, "data_processing") is True


def test_withdrawing_consent_is_a_new_record_not_an_overwrite():
    user_id = create_db_user("patient")
    record_consent(user_id, "data_processing", granted=True)
    record_consent(user_id, "data_processing", granted=False)

    assert has_consented(user_id, "data_processing") is False
    history = get_consent_history(user_id)
    assert len(history) == 2
    assert history[0].granted is True
    assert history[1].granted is False


def test_get_current_consent_returns_the_most_recent_record():
    user_id = create_db_user("patient")
    record_consent(user_id, "data_processing", granted=True)
    record_consent(user_id, "data_processing", granted=True)
    current = get_current_consent(user_id, "data_processing")
    assert current is not None
    assert current.granted is True


def test_consent_types_are_independent():
    user_id = create_db_user("patient")
    record_consent(user_id, "data_processing", granted=True)
    assert has_consented(user_id, "data_processing") is True
    assert has_consented(user_id, "marketing_communications") is False


def test_get_consent_history_empty_for_new_user():
    user_id = create_db_user("patient")
    assert get_consent_history(user_id) == []
