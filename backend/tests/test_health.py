"""Liveness vs. readiness — see app/api/health.py for why these are two
different checks, not two names for the same one."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_is_always_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_reports_ok_when_db_and_redis_are_reachable():
    # In the test suite, both SQLite and fakeredis are always "reachable"
    # (fakeredis is in-process, the SQLite file was just migrated) — this
    # exercises the healthy path; a real DB/Redis outage isn't simulable
    # without tearing down the fakes mid-test, which isn't worth the
    # complexity here.
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": True, "redis": True}
