"""MaxBodySizeMiddleware — see app/core/request_limits.py."""

from fastapi.testclient import TestClient

from app.core.request_limits import MAX_BODY_BYTES
from app.main import app

client = TestClient(app)


def test_normal_sized_request_is_unaffected():
    r = client.post("/triage/intake", json={"text": "I have a mild cough"})
    assert r.status_code == 200


def test_oversized_request_is_rejected_with_413():
    oversized_text = "x" * (MAX_BODY_BYTES + 1)
    r = client.post(
        "/triage/intake",
        content=f'{{"text": "{oversized_text}"}}'.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]


def test_photo_upload_path_is_exempt_from_the_json_body_cap():
    # A real photo upload legitimately exceeds MAX_BODY_BYTES (1 MiB) —
    # see app/core/config.py's MAX_PHOTO_BYTES (5 MiB) and
    # app/core/request_limits.py's docstring for why this middleware
    # exempts /photos POST paths rather than raising the global cap.
    # This only proves the middleware doesn't 413 an over-1-MiB body on
    # that path via Content-Length — the actual endpoint (unauthenticated
    # here, so a 401/404 is the real response) still applies its own cap;
    # see test_symptom_photos_api.py for the authenticated, full-flow version.
    oversized_body = b"x" * (MAX_BODY_BYTES + 1)
    r = client.post(
        "/audit/1/photos",
        content=oversized_body,
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code != 413
