# Phase 4 deep-dive: auth / RBAC

## What's built

- `app/models/user.py` — `User` (email, hashed_password, role). Three
  roles: `patient` (no special access), `provider` (can read the audit
  trail), `admin` (currently equivalent to provider — kept distinct for
  future admin-only actions like user management).
- `app/core/security.py` — password hashing (PBKDF2-HMAC-SHA256 via
  stdlib `hashlib`, no bcrypt/argon2 dependency) and JWT issuance/
  verification (PyJWT, HS256, 24h expiry).
- `app/api/auth.py` — `POST /auth/register`, `POST /auth/login`. Login
  returns the same 401 for "no such user" and "wrong password" —
  deliberately not distinguishing them, to avoid leaking which emails have
  accounts.
- `app/api/deps.py` — `get_current_user` (validates the bearer token) and
  `require_role(*roles)` (a dependency factory for gating routes by role).
- `app/api/audit.py` — `GET /audit/recent` now requires
  `require_role("provider", "admin")` instead of being open, closing the
  gap flagged explicitly in `docs/phase4a-audit-persistence.md`.
- `app/models/revoked_token.py` + `app/services/token_revocation.py` +
  `POST /auth/logout` — a DB-backed token blocklist, closing the
  "no revocation" gap this doc originally flagged (see below). Every
  access token now carries a unique `jti` claim; logout revokes it, and
  `get_current_user` checks the blocklist on every request.

Verified live against a real running server (not just TestClient): no
token → 401, a patient's token → 403, a provider's token → 200 with real
audit data; and (added in the revocation pass) the exact same token that
worked before `/auth/logout` gets `401 {"detail": "token has been
revoked"}` immediately after, with no wait for natural expiry.

## Follow-up pass: closing self-service role selection

This was the biggest flagged gap from the first auth pass, closed in a
follow-up:

- `/auth/register` no longer accepts a `role` field at all — every new
  account is a `patient`, full stop. Verified live: a register request
  that still sends `"role": "admin"` (simulating an old client, or an
  attacker probing the previously-open path) gets `"role":"patient"` back
  regardless.
- `app/api/admin.py` adds `GET /admin/users` and
  `PATCH /admin/users/{id}/role`, both gated to `admin` only, so role
  assignment is now genuinely admin-controlled.
- `scripts/create_admin.py` is the one-time bootstrap for the *first*
  admin — there's no admin yet to promote anyone when a deployment is
  brand new, so this script inserts (or promotes) an admin account
  directly via the DB, run once by whoever controls the deployment. Uses
  `getpass` rather than an argv password so it doesn't end up in shell
  history.
- The frontend's `/admin` page (built alongside this) lists users and
  lets an admin change roles via a dropdown — verified live end-to-end: a
  freshly registered patient, promoted to provider through the UI, shows
  `"role":"provider"` on a direct backend login check immediately after.

Existing tests that used to get a provider/admin token via self-service
registration now go through the real promotion path instead (see
`tests/_auth_helpers.py`'s `_bootstrap_admin`/`promote` — they bootstrap
one admin directly in the DB the same way the CLI script does, then use
the actual `PATCH /admin/users/{id}/role` endpoint), so the tests exercise
the real flow rather than a shortcut around it.

## Follow-up pass: refresh tokens

Access tokens shrank from a flat 24h to 1h, and a proper refresh flow was
added rather than just shortening the window and calling it done:

- `create_refresh_token()` (security.py) issues a separate JWT (`type:
  "refresh"`, 7-day expiry) alongside every access token. `app/models/refresh_token.py`
  tracks issued refresh tokens server-side (not just revoked ones, unlike
  the access-token blocklist) — necessary for rotation-with-reuse-detection,
  which needs to know "was this specific token actually issued and not yet
  consumed," not just "is the signature valid."
- **Rotation**: `POST /auth/refresh` consumes the presented refresh token
  (marks it `used_at`) and issues a brand-new access+refresh pair. The old
  refresh token can never be used again.
- **Reuse detection**: presenting an already-used refresh token doesn't
  just fail — it revokes *every* refresh token for that user, on the
  theory that a replayed token is a strong signal of theft (the legitimate
  client already rotated past it). Verified live: rotate once, replay the
  old token (401, expected), then try the *new* token from the legitimate
  rotation — also 401, proving reuse detection nukes the whole session,
  not just the replay attempt.
- **Type boundary enforced both ways**: `get_current_user` (deps.py) now
  rejects any token whose `type` claim isn't `"access"`, so a stolen
  refresh token can't be used directly as an API credential. Symmetrically,
  `/auth/refresh` rejects a `type: "access"` token. Verified live and in
  tests (`test_access_token_cannot_be_used_as_a_refresh_token`,
  `test_refresh_token_cannot_be_used_as_an_access_token`).
- **Role re-read on refresh**: `rotate_refresh_token()` looks up the
  user's *current* role from the DB rather than re-signing the old token's
  role claim — so a promotion via `/admin/users/{id}/role` now takes
  effect on the next refresh (up to 1h), not only on a fresh login. This
  narrows (but doesn't eliminate) the "role changes don't invalidate
  existing tokens" gap noted below.
- **Logout revokes both tokens.** `POST /auth/logout` now optionally
  accepts `{"refresh_token": "..."}` and revokes it alongside the access
  token — otherwise the refresh token would keep working and could mint a
  fresh access token right after "logging out." The frontend's logout
  button sends both.
- **What the frontend does NOT do yet**: proactively call
  `refreshAccessToken()` before the access token expires. `authFetch()`
  (see below) does retry reactively on a 401, but there's no timer-based
  or before-expiry refresh — a session only refreshes the moment a stale
  token actually fails a request.

## Follow-up pass: frontend auto-refresh

Closes the "What the frontend does NOT do yet" gap above: `authFetch()`
in `frontend/lib/api.ts` (the shared helper `fetchUsers`/`promoteUserRole`/
`fetchRecentAuditRecords` all go through) now retries once on a 401 —
attempt the request, and if it comes back 401, call `trySilentRefresh()`
(which calls `refreshAccessToken()`, saves the new pair via `saveAuth()`),
then retry the original request with the new access token. A 403 is left
alone (a valid-but-wrong-role token refreshing won't fix a role problem).

**A real concurrency bug was found and fixed while verifying this live**,
not just in unit tests: opening `/audit` with a corrupted access token
(simulating expiry) but a valid refresh token, the page rendered
successfully — but `localStorage` came back completely empty immediately
after. Two `authFetch` calls (React StrictMode's dev-mode double-effect
reproduces this reliably; two genuinely concurrent authenticated requests
after real expiry would too) each hit a 401 and each independently called
`refreshAccessToken()` with the SAME refresh token. Refresh tokens rotate
on every use (see the refresh-token section above), so the second call
presented an already-consumed token — the backend's reuse detection
correctly flagged it as theft and revoked the session, and the losing
call's `catch` block ran `clearAuth()`, wiping out the tokens the winning
call had just saved moments earlier.

Fixed with a single-flight pattern: a module-level `inFlightRefresh`
promise that every concurrent caller awaits instead of each starting its
own refresh call. Verified by repeating the exact same corrupted-token
scenario: the network log now shows two 401s but only ONE
`POST /auth/refresh`, and `localStorage` still holds valid tokens
afterward. This is the same class of bug as the backend refresh-token
race found by the code review (concurrent requests racing a rotate-once
resource) — the fix needed is structurally the same idea (make the
critical section execute exactly once, not "race and let one win"), just
implemented in-process (a shared promise) rather than at the database
(an atomic conditional UPDATE), since there's no shared DB on the client.

## Deliberate prototype shortcuts still open (flagged, not hidden)

- **Role changes still don't fully invalidate existing tokens.** Narrowed
  by the refresh-token pass above (role updates now propagate on refresh,
  up to 1h, instead of only at 24h), but a user who never refreshes their
  session (e.g. a short-lived script using only the access token) still
  keeps their original role claim until that token's natural 1h expiry or
  explicit revocation.
- **Hand-rolled password hashing** (PBKDF2 via stdlib) instead of a
  maintained library like passlib+argon2/bcrypt. Functionally fine today,
  but a maintained library tracks parameter recommendations over time in
  a way a fixed iteration count frozen in this session's code won't.
- **Revocation/refresh-tracking is DB-backed, which doesn't scale.**
  Every protected request now costs a SQL lookup against
  `revoked_tokens` to check the token's `jti`, and every refresh costs a
  lookup + write against `refresh_tokens`. Fine at prototype scale; a real
  deployment would use a fast in-memory store (Redis) for both instead of
  SQL tables on the hot path. There's also no purge job for expired rows
  in either table yet — `expires_at` is stored on both specifically so
  one can be added without a migration, but both tables grow unbounded
  until then.
- **No frontend auto-refresh.** See "What the frontend does NOT do yet"
  above.
- **No per-row access scoping.** Any provider can see every patient's
  audit records — there's no provider-to-patient panel concept yet. Fine
  for a single-clinic prototype, not for anything with multiple
  independent provider organizations (multi-tenancy, still open).
- **Dev-default `SECRET_KEY`.** `security.py` raises at import time if
  `ENVIRONMENT=production` and the JWT secret is still the insecure
  default — a real deployment must set `SECRET_KEY`, and this is enforced
  in code, not just documented.

## Why gate only `/audit/recent` for now

Patients don't need accounts to get a triage response — `/triage/evaluate`
and `/triage/intake` are intentionally left open, matching the product's
actual shape (anyone can describe symptoms without signing up first).
Auth exists specifically for the provider-facing side, which starts and
currently ends at the audit trail. As the provider dashboard grows (Phase
4 remainder), new routes should default to `require_role(...)` from the
start rather than being retrofitted the way `/audit/recent` was.
