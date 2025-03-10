"""Dedicated tests for the rate limiter — the rest of the suite runs with
it disabled (see conftest.py's RATE_LIMIT_ENABLED=0 and
app/core/rate_limit.py for why: starlette's TestClient always presents
the same synthetic remote address, so leaving it on for every test would
throttle unrelated tests, not just these).

Each test explicitly flips `limiter.enabled = True` for its own scope and
restores it afterward, so this file can run in any order relative to the
rest of the suite without leaking rate-limit state into other tests.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from tests._auth_helpers import _TEST_PASSWORD

client = TestClient(app)


@pytest.fixture
def rate_limiting_enabled():
    limiter.enabled = True
    limiter.reset()  # clear any counts from a prior run of this fixture
    yield
    limiter.enabled = False


def test_register_is_rate_limited_per_ip(rate_limiting_enabled):
    # 5/minute on /auth/register (app/api/auth.py) — the 6th distinct
    # registration attempt from the same client within a minute must 429.
    for i in range(5):
        r = client.post(
            "/auth/register",
            json={"email": f"ratelimit-register-{i}@example.com", "password": _TEST_PASSWORD},
        )
        assert r.status_code == 201, r.text

    r = client.post(
        "/auth/register",
        json={"email": "ratelimit-register-overflow@example.com", "password": _TEST_PASSWORD},
    )
    assert r.status_code == 429


def test_login_is_rate_limited_per_ip(rate_limiting_enabled):
    # 10/minute on /auth/login — use wrong-password attempts (still hits
    # the rate limiter regardless of whether the login itself succeeds).
    for _ in range(10):
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
        assert r.status_code == 401  # rejected on credentials, not yet rate-limited

    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert r.status_code == 429


def test_rate_limit_response_has_a_clear_detail():
    limiter.enabled = True
    limiter.reset()
    try:
        for i in range(5):
            client.post(
                "/auth/register",
                json={"email": f"ratelimit-detail-{i}@example.com", "password": _TEST_PASSWORD},
            )
        r = client.post(
            "/auth/register",
            json={"email": "ratelimit-detail-overflow@example.com", "password": _TEST_PASSWORD},
        )
        assert r.status_code == 429
        assert "rate limit" in r.json().get("error", "").lower()
    finally:
        limiter.enabled = False


def test_rate_limiter_disabled_by_default_for_the_rest_of_the_suite():
    # Sanity check on the fixture teardown itself: after the tests above
    # ran and restored limiter.enabled = False, hammering an endpoint well
    # past any of the limits above must NOT 429 — this is what keeps the
    # rest of the test suite (hundreds of /auth/register calls across many
    # files) from being throttled.
    assert limiter.enabled is False
    for i in range(20):
        r = client.post(
            "/auth/register",
            json={"email": f"no-rate-limit-check-{i}@example.com", "password": _TEST_PASSWORD},
        )
        assert r.status_code == 201
