import pytest

from app.services.patient_panel import (
    AssignmentAlreadyExists,
    AssignmentNotFound,
    UserNotFound,
    assign_patient,
    is_on_panel,
    list_all_assignments,
    list_panel_patient_ids,
    unassign_patient,
)
from tests._auth_helpers import create_db_user


def test_assign_patient_creates_assignment():
    provider_id = create_db_user("provider")
    patient_id = create_db_user("patient")
    assignment = assign_patient(provider_id=provider_id, patient_id=patient_id)
    assert assignment.provider_id == provider_id
    assert assignment.patient_id == patient_id


def test_duplicate_assignment_raises():
    provider_id = create_db_user("provider")
    patient_id = create_db_user("patient")
    assign_patient(provider_id=provider_id, patient_id=patient_id)
    with pytest.raises(AssignmentAlreadyExists):
        assign_patient(provider_id=provider_id, patient_id=patient_id)


def test_same_patient_can_be_assigned_to_different_providers():
    provider_a = create_db_user("provider")
    provider_b = create_db_user("provider")
    patient_id = create_db_user("patient")
    assign_patient(provider_id=provider_a, patient_id=patient_id)
    # Should not raise — the unique constraint is on the (provider, patient)
    # pair, not on patient alone; a patient can have more than one provider.
    assign_patient(provider_id=provider_b, patient_id=patient_id)


def test_assign_patient_rejects_unknown_provider():
    patient_id = create_db_user("patient")
    with pytest.raises(UserNotFound):
        assign_patient(provider_id=999999, patient_id=patient_id)


def test_assign_patient_rejects_unknown_patient():
    provider_id = create_db_user("provider")
    with pytest.raises(UserNotFound):
        assign_patient(provider_id=provider_id, patient_id=999999)


def test_list_panel_patient_ids_returns_only_that_providers_patients():
    provider_a = create_db_user("provider")
    provider_b = create_db_user("provider")
    patient_1 = create_db_user("patient")
    patient_2 = create_db_user("patient")
    patient_3 = create_db_user("patient")
    assign_patient(provider_id=provider_a, patient_id=patient_1)
    assign_patient(provider_id=provider_a, patient_id=patient_2)
    assign_patient(provider_id=provider_b, patient_id=patient_3)

    assert set(list_panel_patient_ids(provider_a)) == {patient_1, patient_2}
    assert set(list_panel_patient_ids(provider_b)) == {patient_3}


def test_list_panel_patient_ids_empty_for_unassigned_provider():
    assert list_panel_patient_ids(999999) == []


def test_is_on_panel():
    provider_id = create_db_user("provider")
    patient_id = create_db_user("patient")
    other_patient_id = create_db_user("patient")
    assign_patient(provider_id=provider_id, patient_id=patient_id)
    assert is_on_panel(provider_id, patient_id) is True
    assert is_on_panel(provider_id, other_patient_id) is False


def test_unassign_removes_assignment():
    provider_id = create_db_user("provider")
    patient_id = create_db_user("patient")
    assignment = assign_patient(provider_id=provider_id, patient_id=patient_id)
    unassign_patient(assignment.id)
    assert is_on_panel(provider_id, patient_id) is False


def test_unassign_unknown_raises_not_found():
    with pytest.raises(AssignmentNotFound):
        unassign_patient(999999)


def test_list_all_assignments_includes_everything():
    provider_id = create_db_user("provider")
    patient_id = create_db_user("patient")
    assign_patient(provider_id=provider_id, patient_id=patient_id)
    all_assignments = list_all_assignments()
    assert any(a.provider_id == provider_id and a.patient_id == patient_id for a in all_assignments)
