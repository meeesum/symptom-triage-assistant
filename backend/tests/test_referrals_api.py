"""API-level tests for referral & appointment tracking — see
app/api/referrals.py and docs/phase7c-referral-tracking.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def _get_record_id_for_patient(patient_token: str, text: str) -> int:
    r = client.post(
        "/triage/intake",
        json={"text": text},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200, r.text
    admin_token = register_and_get_token(client, role="admin")
    records = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    return records[0]["id"]


def test_patient_cannot_create_referral():
    token = register_and_get_token(client, role="patient")
    record_id = _get_record_id_for_patient(token, "I have a mild cough")
    r = client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_provider_can_create_and_advance_referral_on_panel_patient():
    admin_token = register_and_get_token(client, role="admin")
    provider_email, _ = register_new_patient(client)
    provider_token = promote(client, provider_email, "provider")
    patient_email, patient_token = register_new_patient(client)

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)
    client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    create_r = client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {provider_token}"}
    )
    assert create_r.status_code == 201, create_r.text
    assert create_r.json()["status"] == "referred"

    patch_r = client.patch(
        f"/audit/{record_id}/referral",
        json={"status": "scheduled"},
        headers={"Authorization": f"Bearer {provider_token}"},
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["status"] == "scheduled"
    assert len(patch_r.json()["history"]) == 2


def test_referral_cannot_move_backward():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"}
    )
    client.patch(
        f"/audit/{record_id}/referral",
        json={"status": "seen"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    r = client.patch(
        f"/audit/{record_id}/referral",
        json={"status": "scheduled"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 409


def test_duplicate_referral_returns_conflict():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"}
    )
    r = client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 409


def test_provider_not_on_panel_cannot_create_referral():
    _outsider_email, outsider_token = register_new_patient(client)
    outsider_token = promote(client, _outsider_email, "provider")

    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    r = client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert r.status_code == 404


def test_get_referral_for_record_with_none_returns_404():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "I have a mild cough")

    r = client.get(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 404


def test_invalid_status_value_returns_422():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    client.post(
        f"/audit/{record_id}/referral", headers={"Authorization": f"Bearer {admin_token}"}
    )
    r = client.patch(
        f"/audit/{record_id}/referral",
        json={"status": "not_a_real_status"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422
