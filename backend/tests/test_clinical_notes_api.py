"""API-level tests for clinical notes — see app/api/clinical_notes.py and
docs/phase7b-clinical-notes.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def _get_record_id_for_patient(patient_token: str, text: str) -> int:
    """Submits a triage as the given patient and returns the resulting
    audit record's id, found via an admin's unrestricted /audit/recent."""
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


def test_patient_cannot_create_note():
    token = register_and_get_token(client, role="patient")
    record_id = _get_record_id_for_patient(token, "I have a mild cough")
    r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "trying to add a note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_provider_on_patients_panel_can_add_and_read_a_note():
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

    r = client.post(
        "/triage/intake",
        json={"text": "sudden chest pain and sweating"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200

    records = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()
    record_id = records[0]["id"]

    create_r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "Called patient, advised ER visit.", "note_type": "clinical_impression"},
        headers={"Authorization": f"Bearer {provider_token}"},
    )
    assert create_r.status_code == 201, create_r.text
    assert create_r.json()["author_id"] == provider_id

    get_r = client.get(
        f"/audit/{record_id}/notes", headers={"Authorization": f"Bearer {provider_token}"}
    )
    assert get_r.status_code == 200
    assert len(get_r.json()) == 1


def test_provider_not_on_panel_cannot_add_note():
    _outsider_email, outsider_token = register_new_patient(client)
    outsider_token = promote(client, _outsider_email, "provider")

    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "shouldn't be able to see this"},
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert r.status_code == 404


def test_provider_can_add_note_on_anonymous_record():
    r = client.post("/triage/evaluate", json={"symptom_ids": ["chest_pain", "shortness_of_breath"]})
    assert r.status_code == 200

    admin_token = register_and_get_token(client, role="admin")
    records = client.get(
        "/audit/recent?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    record_id = records[0]["id"]

    provider_token = register_and_get_token(client, role="provider")
    r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "Anonymous case, no panel needed."},
        headers={"Authorization": f"Bearer {provider_token}"},
    )
    assert r.status_code == 201


def test_note_on_unknown_record_returns_404():
    token = register_and_get_token(client, role="provider")
    r = client.post(
        "/audit/999999999/notes",
        json={"body": "n/a"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_invalid_note_type_returns_422():
    token = register_and_get_token(client, role="provider")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "n/a", "note_type": "not_a_real_type"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_admin_can_add_note_regardless_of_panel():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    record_id = _get_record_id_for_patient(patient_token, "sudden chest pain and sweating")

    r = client.post(
        f"/audit/{record_id}/notes",
        json={"body": "Admin oversight note."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201
