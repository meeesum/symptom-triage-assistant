from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token, register_new_patient

client = TestClient(app)


def _admin_token():
    return register_and_get_token(client, role="admin")


def test_patient_cannot_create_assignment():
    token = register_and_get_token(client, role="patient")
    r = client.post(
        "/panel/assignments",
        json={"provider_id": 1, "patient_id": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_provider_cannot_create_assignment():
    token = register_and_get_token(client, role="provider")
    r = client.post(
        "/panel/assignments",
        json={"provider_id": 1, "patient_id": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_can_assign_a_real_provider_and_patient():
    admin_token = _admin_token()
    provider_email, _ = register_new_patient(client)
    from tests._auth_helpers import promote

    promote(client, provider_email, "provider")
    patient_email, _ = register_new_patient(client)

    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)

    r = client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider_id"] == provider_id
    assert body["patient_id"] == patient_id


def test_assignment_rejects_wrong_roles():
    admin_token = _admin_token()
    # Two patients — neither is a provider, so provider_id is wrong-roled.
    patient1_email, _ = register_new_patient(client)
    patient2_email, _ = register_new_patient(client)
    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    p1 = next(u["id"] for u in users if u["email"] == patient1_email)
    p2 = next(u["id"] for u in users if u["email"] == patient2_email)

    r = client.post(
        "/panel/assignments",
        json={"provider_id": p1, "patient_id": p2},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422


def test_provider_can_see_their_own_panel():
    admin_token = _admin_token()
    provider_email, provider_token = register_new_patient(client)
    from tests._auth_helpers import promote

    provider_token = promote(client, provider_email, "provider")
    patient_email, _ = register_new_patient(client)

    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)

    client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    r = client.get("/panel/mine", headers={"Authorization": f"Bearer {provider_token}"})
    assert r.status_code == 200
    assert any(p["email"] == patient_email for p in r.json())


def test_patient_cannot_view_any_panel():
    token = register_and_get_token(client, role="patient")
    r = client.get("/panel/mine", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_delete_an_assignment():
    admin_token = _admin_token()
    provider_email, _ = register_new_patient(client)
    from tests._auth_helpers import promote

    promote(client, provider_email, "provider")
    patient_email, _ = register_new_patient(client)
    users = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    provider_id = next(u["id"] for u in users if u["email"] == provider_email)
    patient_id = next(u["id"] for u in users if u["email"] == patient_email)

    assignment_id = client.post(
        "/panel/assignments",
        json={"provider_id": provider_id, "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()["id"]

    r = client.delete(
        f"/panel/assignments/{assignment_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 204

    r2 = client.delete(
        f"/panel/assignments/{assignment_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r2.status_code == 404
