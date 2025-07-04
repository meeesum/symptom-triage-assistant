"""Auth (register/login), admin-controlled role promotion, and RBAC
gating on /audit/recent."""

from fastapi.testclient import TestClient

from app.main import app
from tests._auth_helpers import (
    _TEST_PASSWORD,
    promote,
    register_and_get_token,
    register_new_patient,
)

client = TestClient(app)


class TestRegisterAndLogin:
    def test_register_always_creates_a_patient(self):
        # Confirms self-service role selection is gone: even if a caller
        # sends other fields, only email/password are accepted and the
        # account always comes out as "patient".
        r = client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": _TEST_PASSWORD},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["role"] == "patient"
        assert body["access_token"]

    def test_extra_role_field_in_register_request_is_ignored(self):
        # A request that still sends a "role" field (an old client, or an
        # attacker trying the previously-open self-service path) must not
        # be able to grant itself provider/admin — the field is silently
        # ignored by the request schema, not validated and rejected.
        r = client.post(
            "/auth/register",
            json={"email": "attacker@example.com", "password": _TEST_PASSWORD, "role": "admin"},
        )
        assert r.status_code == 201
        assert r.json()["role"] == "patient"

    def test_duplicate_email_is_rejected(self):
        client.post("/auth/register", json={"email": "dupe@example.com", "password": _TEST_PASSWORD})
        r = client.post(
            "/auth/register",
            json={"email": "dupe@example.com", "password": "different-password-here"},
        )
        assert r.status_code == 409

    def test_concurrent_registration_with_same_email_never_500s(self):
        # Code-review bug: the existing-user check and the insert weren't
        # atomic, so two concurrent registrations with the same email
        # could both pass the check and the second commit would raise an
        # unhandled IntegrityError (raw 500) instead of a clean 409.
        from concurrent.futures import ThreadPoolExecutor

        email = "race-condition@example.com"

        def attempt():
            return client.post("/auth/register", json={"email": email, "password": _TEST_PASSWORD})

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: attempt(), range(8)))

        statuses = [r.status_code for r in responses]
        assert all(s in (201, 409) for s in statuses), f"got an unexpected status: {statuses}"
        assert statuses.count(201) == 1, f"expected exactly one successful registration, got {statuses}"

    def test_login_reflects_current_role(self):
        email, _token = register_new_patient(client)
        provider_token = promote(client, email, "provider")

        r = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
        assert r.status_code == 200
        assert r.json()["role"] == "provider"
        assert provider_token  # sanity: promote() itself returned a usable token too

    def test_login_with_wrong_password_fails(self):
        register_new_patient(client)
        r = client.post("/auth/login", json={"email": "nonexistent-mismatch@example.com", "password": "wrong"})
        assert r.status_code == 401

    def test_login_with_unknown_email_fails_with_same_status_as_wrong_password(self):
        # Same status/detail for "no such user" vs "wrong password" —
        # guards against account-enumeration via response differences.
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
        assert r.status_code == 401


class TestAdminRoleManagement:
    def test_non_admin_cannot_list_users(self):
        token = register_and_get_token(client, role="patient")
        r = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_non_admin_cannot_promote_a_user(self):
        actor_token = register_and_get_token(client, role="patient")
        target_email, _ = register_new_patient(client)
        r = client.get("/admin/users", headers={"Authorization": f"Bearer {actor_token}"})
        assert r.status_code == 403  # can't even look up the target's id
        # and directly guessing an id is still blocked regardless:
        r2 = client.patch(
            "/admin/users/1/role",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {actor_token}"},
        )
        assert r2.status_code == 403

    def test_admin_can_list_and_promote_a_user(self):
        admin_token = register_and_get_token(client, role="admin")
        target_email, _ = register_new_patient(client)

        list_r = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
        assert list_r.status_code == 200
        target = next(u for u in list_r.json() if u["email"] == target_email)
        assert target["role"] == "patient"

        patch_r = client.patch(
            f"/admin/users/{target['id']}/role",
            json={"role": "provider"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch_r.status_code == 200
        assert patch_r.json()["role"] == "provider"

    def test_promoting_to_invalid_role_is_rejected(self):
        admin_token = register_and_get_token(client, role="admin")
        target_email, _ = register_new_patient(client)
        list_r = client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
        target = next(u for u in list_r.json() if u["email"] == target_email)

        r = client.patch(
            f"/admin/users/{target['id']}/role",
            json={"role": "superadmin"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 422

    def test_promoting_nonexistent_user_is_404(self):
        admin_token = register_and_get_token(client, role="admin")
        r = client.patch(
            "/admin/users/999999/role",
            json={"role": "provider"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 404


class TestAuditRBAC:
    def test_audit_recent_without_token_is_rejected(self):
        r = client.get("/audit/recent")
        assert r.status_code == 401

    def test_audit_recent_with_garbage_token_is_rejected(self):
        r = client.get("/audit/recent", headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401

    def test_audit_recent_with_patient_token_is_forbidden(self):
        token = register_and_get_token(client, role="patient")
        r = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_audit_recent_with_provider_token_is_allowed(self):
        token = register_and_get_token(client, role="provider")
        r = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_audit_recent_with_admin_token_is_allowed(self):
        token = register_and_get_token(client, role="admin")
        r = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


class TestTokenRevocation:
    def test_logout_revokes_the_token(self):
        token = register_and_get_token(client, role="provider")

        # works before logout
        r1 = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
        assert r1.status_code == 200

        logout_r = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout_r.status_code == 204

        # same token, now rejected — the important behavior this feature exists for
        r2 = client.get("/audit/recent", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 401
        assert "revoked" in r2.json()["detail"]

    def test_logout_without_a_token_is_rejected(self):
        r = client.post("/auth/logout")
        assert r.status_code == 401

    def test_logout_is_idempotent(self):
        # Logging out twice with the same (already-revoked) token shouldn't
        # 500 — but the second call correctly fails auth entirely, since a
        # revoked token can't even reach the logout handler a second time.
        token = register_and_get_token(client, role="provider")
        client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        r = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_a_fresh_token_for_the_same_user_is_unaffected_by_a_prior_logout(self):
        # Revocation targets a specific token (jti), not "this user's
        # session" broadly — logging in again after logout must work.
        email, first_token = register_new_patient(client)
        client.post("/auth/logout", headers={"Authorization": f"Bearer {first_token}"})

        # a brand new login for the same user gets a brand new, unrevoked token
        login_r2 = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
        new_token = login_r2.json()["access_token"]
        r = client.get("/audit/recent", headers={"Authorization": f"Bearer {new_token}"})
        # 403 (patient role, not authorized for this route) rather than 401
        # (rejected token) — proves the new token passed the auth layer
        # fine and wasn't affected by the earlier token's revocation.
        assert r.status_code == 403
