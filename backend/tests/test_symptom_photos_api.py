"""API-level tests for symptom photo upload/review — see
app/api/symptom_photos.py and docs/phase9c-symptom-photo-upload.md.
"""

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from tests._auth_helpers import promote, register_and_get_token, register_new_patient

client = TestClient(app)


def _jpeg_bytes(color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), color).save(buf, format="JPEG")
    return buf.getvalue()


def _submit_and_get_record_id(token: str, text: str = "a rash on my arm") -> int:
    r = client.post(
        "/triage/intake", json={"text": text}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    record_id = r.json()["audit_record_id"]
    assert record_id is not None
    return record_id


def test_triage_intake_returns_audit_record_id_for_logged_in_patient():
    token = register_and_get_token(client, role="patient")
    r = client.post(
        "/triage/intake",
        json={"text": "I have a mild cough"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json()["audit_record_id"], int)


def test_patient_can_upload_photo_to_their_own_record():
    token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(token)

    r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["audit_record_id"] == record_id
    assert body["content_type"] == "image/jpeg"


def test_patient_cannot_upload_to_another_patients_record():
    owner_token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(owner_token)

    _other_email, other_token = register_new_patient(client)
    r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 404


def test_patient_cannot_upload_to_an_anonymous_record():
    r = client.post("/triage/evaluate", json={"symptom_ids": ["rash"]})
    assert r.status_code == 200
    record_id = r.json()["audit_record_id"]

    token = register_and_get_token(client, role="patient")
    r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_upload_rejects_non_image_content():
    token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(token)

    r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("notes.txt", b"just some plain text" * 20, "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_upload_rejects_oversized_file():
    token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(token)

    # Rather than allocating a real 5MB+ image to cross the default cap,
    # temporarily lower the cap itself — `_read_capped` reads
    # `app.api.symptom_photos.MAX_PHOTO_BYTES` at call time, so patching
    # the module attribute (not the env var, which is only read once at
    # import) is enough.
    import app.api.symptom_photos as photos_api

    original = photos_api.MAX_PHOTO_BYTES
    photos_api.MAX_PHOTO_BYTES = 10  # bytes — any real JPEG exceeds this
    try:
        r = client.post(
            f"/audit/{record_id}/photos",
            files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 413
    finally:
        photos_api.MAX_PHOTO_BYTES = original


def test_upload_larger_than_the_global_json_body_cap_still_succeeds():
    # A real photo (even a modest one) commonly exceeds the 1 MiB cap
    # MaxBodySizeMiddleware applies to ordinary JSON bodies — this proves
    # the /photos path's exemption from that cap (app/core/
    # request_limits.py) actually works end to end, not just that the
    # middleware unit test above doesn't 413 on Content-Length. 2 MiB is
    # comfortably over the 1 MiB JSON cap and under the 5 MiB photo cap.
    # Random noise, not a solid color — PNG compresses a flat color down
    # to a few KB regardless of pixel dimensions, which defeated an
    # earlier version of this test.
    import random

    rng = random.Random(0)
    pixels = bytes(rng.getrandbits(8) for _ in range(900 * 900 * 3))
    img = Image.frombytes("RGB", (900, 900), pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    large_png = buf.getvalue()
    assert 1 * 1024 * 1024 < len(large_png) < 5 * 1024 * 1024

    token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(token)
    r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.png", large_png, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_provider_on_panel_can_list_and_fetch_photo():
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

    record_id = _submit_and_get_record_id(patient_token)
    upload_r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    photo_id = upload_r.json()["id"]

    list_r = client.get(
        f"/audit/{record_id}/photos", headers={"Authorization": f"Bearer {provider_token}"}
    )
    assert list_r.status_code == 200
    assert len(list_r.json()) == 1

    get_r = client.get(
        f"/audit/{record_id}/photos/{photo_id}",
        headers={"Authorization": f"Bearer {provider_token}"},
    )
    assert get_r.status_code == 200
    assert get_r.headers["content-type"] == "image/jpeg"
    assert get_r.content == _jpeg_bytes()


def test_provider_not_on_panel_cannot_view_photos():
    _outsider_email, outsider_token = register_new_patient(client)
    outsider_token = promote(client, _outsider_email, "provider")

    patient_token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(patient_token)
    client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {patient_token}"},
    )

    r = client.get(
        f"/audit/{record_id}/photos", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert r.status_code == 404


def test_patient_can_delete_their_own_photo():
    token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(token)
    upload_r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    photo_id = upload_r.json()["id"]

    delete_r = client.delete(
        f"/audit/{record_id}/photos/{photo_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert delete_r.status_code == 204

    list_r = client.get(
        f"/audit/{record_id}/photos", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_r.json() == []


def test_patient_cannot_delete_another_patients_photo():
    owner_token = register_and_get_token(client, role="patient")
    record_id = _submit_and_get_record_id(owner_token)
    upload_r = client.post(
        f"/audit/{record_id}/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    photo_id = upload_r.json()["id"]

    _other_email, other_token = register_new_patient(client)
    r = client.delete(
        f"/audit/{record_id}/photos/{photo_id}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 404


def test_photo_on_unknown_record_returns_404():
    token = register_and_get_token(client, role="patient")
    r = client.post(
        "/audit/999999999/photos",
        files={"file": ("rash.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
