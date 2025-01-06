"""API-level tests for retention purge triggering/oversight. See
app/api/retention.py and docs/phase8d-retention-and-purge-jobs.md.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import register_and_get_token

client = TestClient(app)


def test_purge_requires_auth():
    r = client.post("/admin/retention/purge")
    assert r.status_code == 401


def test_patient_cannot_trigger_purge():
    token = register_and_get_token(client, role="patient")
    r = client.post("/admin/retention/purge", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_org_admin_cannot_trigger_purge():
    # Retention is a platform-wide operation, not per-tenant — see
    # app/api/retention.py's module docstring.
    token = register_and_get_token(client, role="org_admin")
    r = client.post("/admin/retention/purge", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_platform_admin_can_trigger_purge_and_see_runs():
    token = register_and_get_token(client, role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/admin/retention/purge", headers=headers)
    assert r.status_code == 202
    assert r.json()["status"] == "enqueued"

    runs_r = client.get("/admin/retention/runs", headers=headers)
    assert runs_r.status_code == 200
    assert len(runs_r.json()) >= 1
