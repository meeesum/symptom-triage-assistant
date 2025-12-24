"""API-level tests for reporting exports — see app/api/reports.py and
docs/phase9d-reporting-exports.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token

client = TestClient(app)


# ---------------------------------------------------------------- exports


def test_patient_cannot_export_csv():
    token = register_and_get_token(client, role="patient")
    r = client.get("/audit/export.csv", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_export_csv():
    token = register_and_get_token(client, role="admin")
    r = client.get("/audit/export.csv", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.splitlines()[0].startswith("id,created_at,tier")


def test_provider_can_export_csv():
    token = register_and_get_token(client, role="provider")
    r = client.get("/audit/export.csv", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_patient_cannot_export_pdf():
    token = register_and_get_token(client, role="patient")
    r = client.get("/audit/analytics/export.pdf", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_export_pdf():
    token = register_and_get_token(client, role="admin")
    r = client.get("/audit/analytics/export.pdf", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF-")


def test_export_days_param_is_clamped():
    token = register_and_get_token(client, role="admin")
    r = client.get("/audit/export.csv?days=9999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200  # doesn't error; app/api/reports.py clamps to 365


# ------------------------------------------------------------- subscription


def test_provider_cannot_manage_report_subscription():
    token = register_and_get_token(client, role="provider")
    r = client.get("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_org_admin_starts_unsubscribed():
    token = register_and_get_token(client, role="org_admin")
    r = client.get("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {
        "subscribed": False,
        "frequency": None,
        "report_format": None,
        "last_sent_at": None,
    }


def test_org_admin_can_subscribe_and_read_it_back():
    token = register_and_get_token(client, role="org_admin")
    put_r = client.put(
        "/reports/subscription",
        json={"frequency": "weekly", "report_format": "pdf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert put_r.status_code == 200
    assert put_r.json()["subscribed"] is True
    assert put_r.json()["frequency"] == "weekly"

    get_r = client.get("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert get_r.json()["frequency"] == "weekly"
    assert get_r.json()["report_format"] == "pdf"


def test_invalid_frequency_rejected():
    token = register_and_get_token(client, role="org_admin")
    r = client.put(
        "/reports/subscription",
        json={"frequency": "hourly", "report_format": "pdf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_invalid_format_rejected():
    token = register_and_get_token(client, role="org_admin")
    r = client.put(
        "/reports/subscription",
        json={"frequency": "weekly", "report_format": "docx"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_org_admin_can_cancel_subscription():
    token = register_and_get_token(client, role="org_admin")
    client.put(
        "/reports/subscription",
        json={"frequency": "weekly", "report_format": "csv"},
        headers={"Authorization": f"Bearer {token}"},
    )
    delete_r = client.delete("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert delete_r.status_code == 204

    get_r = client.get("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert get_r.json()["subscribed"] is False


def test_send_now_requires_an_active_subscription():
    token = register_and_get_token(client, role="org_admin")
    r = client.post(
        "/reports/subscription/send-now", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 404


def test_send_now_queues_and_updates_last_sent_at():
    # REPORT_DELIVERY_SYNC=1 (tests/conftest.py) means this runs inline —
    # by the time the response comes back, last_sent_at is already set.
    token = register_and_get_token(client, role="org_admin")
    client.put(
        "/reports/subscription",
        json={"frequency": "weekly", "report_format": "pdf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    send_r = client.post(
        "/reports/subscription/send-now", headers={"Authorization": f"Bearer {token}"}
    )
    assert send_r.status_code == 202
    assert send_r.json()["status"] == "queued"

    get_r = client.get("/reports/subscription", headers={"Authorization": f"Bearer {token}"})
    assert get_r.json()["last_sent_at"] is not None
