"""Refresh token issuance, rotation, reuse detection, and the access/refresh
type boundary (a refresh token must not work as an API credential, and
vice versa)."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from app.services.refresh_tokens import RefreshTokenInvalid, RefreshTokenReused, rotate_refresh_token
from tests._auth_helpers import _TEST_PASSWORD, register_new_patient

client = TestClient(app)


def test_register_returns_both_token_types():
    _email, _ = register_new_patient(client)
    r = client.post(
        "/auth/register", json={"email": "both-tokens@example.com", "password": _TEST_PASSWORD}
    )
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]


def test_refresh_returns_a_new_access_token():
    email, _access_token = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    refresh_token = login_r.json()["refresh_token"]

    r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # the new access token actually works as a credential
    check_r = client.get("/audit/recent", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert check_r.status_code == 403  # patient role — proves the token was accepted, just not authorized


def test_refresh_token_cannot_be_reused_after_rotation():
    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    old_refresh_token = login_r.json()["refresh_token"]

    first_r = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert first_r.status_code == 200

    second_r = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert second_r.status_code == 401


def test_refresh_token_reuse_revokes_all_sessions_for_that_user():
    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    old_refresh_token = login_r.json()["refresh_token"]

    # rotate once (legitimate use) — this produces a *new* refresh token
    first_r = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    new_refresh_token = first_r.json()["refresh_token"]

    # now replay the OLD (already-rotated-out) token — simulates a thief
    # using a stolen copy after the legitimate client already moved on
    replay_r = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert replay_r.status_code == 401

    # the reuse should have revoked the legitimate new token too — the
    # whole point of reuse detection is nuking every session, not just
    # rejecting the replayed one
    legit_attempt_r = client.post("/auth/refresh", json={"refresh_token": new_refresh_token})
    assert legit_attempt_r.status_code == 401


def test_concurrent_rotation_of_the_same_token_only_lets_one_caller_win():
    # Code-review bug: rotate_refresh_token used a plain select-then-write,
    # so two concurrent requests presenting the SAME not-yet-used token
    # could both read used_at=None before either committed, and both
    # would successfully rotate — defeating reuse detection entirely.
    # Fixed with an atomic conditional UPDATE (see refresh_tokens.py's
    # module docstring). This test calls the service function directly
    # (not through TestClient) from real OS threads so the race is
    # actually exercised, not just asserted about.
    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    token = login_r.json()["refresh_token"]

    results = []

    def attempt():
        try:
            return ("ok", rotate_refresh_token(token))
        except RefreshTokenReused as e:
            return ("reused", e)
        except RefreshTokenInvalid as e:
            return ("invalid", e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: attempt(), range(8)))

    successes = [r for r in results if r[0] == "ok"]
    assert len(successes) == 1, (
        f"expected exactly one winner among concurrent rotations of the same token, got {len(successes)}"
    )


def test_refresh_with_garbage_token_is_rejected():
    r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


def test_access_token_cannot_be_used_as_a_refresh_token():
    _email, access_token = register_new_patient(client)
    r = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert r.status_code == 401


def test_refresh_token_cannot_be_used_as_an_access_token():
    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    refresh_token = login_r.json()["refresh_token"]

    r = client.get("/audit/recent", headers={"Authorization": f"Bearer {refresh_token}"})
    assert r.status_code == 401


def test_logout_with_refresh_token_revokes_it():
    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    access_token = login_r.json()["access_token"]
    refresh_token = login_r.json()["refresh_token"]

    logout_r = client.post(
        "/auth/logout",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_r.status_code == 204

    # the refresh token logout revoked should no longer work
    r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401


def test_refresh_re_reads_role_from_the_database():
    # A role promotion should be picked up on refresh, not just on a full
    # re-login — see refresh_tokens.py's module docstring.
    from tests._auth_helpers import promote

    email, _ = register_new_patient(client)
    login_r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    refresh_token = login_r.json()["refresh_token"]

    promote(client, email, "provider")  # promotes + logs in again, but we ignore that new token

    refresh_r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_r.status_code == 200
    assert refresh_r.json()["role"] == "provider"
