"""GET /audit/recent panel-scoping tests — see app/api/audit.py and
docs/phase7a-patient-panels.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def _submit_triage_as(patient_token: str, text: str) -> None:
    r = client.post(
        "/triage/intake",
        json={"text": text},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert r.status_code == 200, r.text


def test_provider_with_no_panel_does_not_see_a_patient_linked_record():
    # Tests run sequentially (single-threaded pytest, shared SQLite file) —
    # nothing else writes to triage_audit_records between the "before" and
    # "after" reads below, so a count delta reliably isolates the effect
    # of the one new patient-linked row this test creates. The API
    # response itself never exposes patient_id (privacy — see
    # app/api/audit.py), so a before/after count is the only way to test
    # exclusion from outside the service layer.
    provider_token = register_and_get_token(client, role="provider")
    before = client.get(
        "/audit/recent?limit=200", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()

    _patient_email, patient_token = register_new_patient(client)
    _submit_triage_as(patient_token, "sudden chest pain and sweating")

    after = client.get(
        "/audit/recent?limit=200", headers={"Authorization": f"Bearer {provider_token}"}
    ).json()

    assert len(after) == len(before)


def test_provider_sees_panel_patients_audit_records():
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

    _submit_triage_as(patient_token, "sudden chest pain and sweating")

    r = client.get("/audit/recent?limit=200", headers={"Authorization": f"Bearer {provider_token}"})
    assert r.status_code == 200
    assert any(row["matched_rule_id"] == "cardiac_event_pattern" for row in r.json())


def test_admin_sees_everything_regardless_of_panel():
    admin_token = register_and_get_token(client, role="admin")
    patient_email, patient_token = register_new_patient(client)
    _submit_triage_as(patient_token, "sudden chest pain and sweating")

    r = client.get("/audit/recent?limit=200", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert any(row["matched_rule_id"] == "cardiac_event_pattern" for row in r.json())
