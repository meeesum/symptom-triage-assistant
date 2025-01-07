# Phase 5b deep-dive: Redis-backed token tracking

Second epic of the scale-up roadmap's Phase 01 (Production Foundations),
following `docs/phase5-postgres-migration.md`. Closes the gap both
`app/core/security.py` and the old `RevokedToken`/`RefreshToken` models'
docstrings had flagged since Phase 4: "every protected request now costs
a DB lookup, which doesn't scale past a prototype," plus "no purge job
for expired blocklist rows yet, the table grows unbounded."

## What's built

- `app/core/redis_client.py` — a module-level singleton client (same
  pattern as `engine` in `app/core/db.py`). Real Redis by default
  (`REDIS_URL`), or `fakeredis` (an in-memory, pure-Python Redis
  implementation) when `REDIS_FAKE=1` — the same "zero-setup default,
  real backing service optional" pattern already used for SQLite/Postgres
  and TF-IDF/dense-embeddings.
- `app/services/token_revocation.py` — rewritten to store each revoked
  access token as `revoked:{jti}`, TTL'd to exactly the time remaining
  until that token's own `exp` claim. Once the JWT would fail signature/
  expiry validation on its own, the blocklist entry is worthless — Redis's
  own expiry removes it. There's no purge job because there's no table to
  need one.
- `app/services/refresh_tokens.py` — rewritten to track issued refresh
  tokens as `refresh:{jti}` (value: `"{user_id}"` unused, `"used:{user_id}"`
  once claimed) plus a per-user `refresh_by_user:{user_id}` set for mass
  revocation on reuse detection. The public functions
  (`issue_refresh_token`, `rotate_refresh_token`, `revoke_refresh_token`)
  kept the exact same signatures and exception types
  (`RefreshTokenInvalid`, `RefreshTokenReused`) as the SQL version — callers
  in `app/api/auth.py` didn't need to change at all.
- `app/models/refresh_token.py` and `app/models/revoked_token.py` —
  **deleted**. `migrations/versions/*_move_token_tracking_to_redis.py` is
  a real Alembic migration dropping both tables — generated via
  `alembic revision --autogenerate` after removing the models from
  `migrations/env.py`'s imports, same workflow as the initial migration,
  just in the other direction.
- `docker-compose.yml` — added a `redis` service alongside `postgres`.

## The atomicity trick: same guarantee, different primitive

The SQL version's race-condition fix (a code-review finding from an
earlier pass) used a single conditional `UPDATE ... WHERE used_at IS NULL`
so two concurrent requests claiming the same refresh token couldn't both
win. Redis has no transactions in the same sense, but it has an equivalent
atomic primitive: `SET key value XX GET` — `XX` only writes if the key
already exists, `GET` atomically returns the value from *before* this
write, and both happen as one indivisible command. That's exactly
"check-and-mark-used in one step," no Lua scripting required:

```python
old_value = redis_client.set(key, f"used:{user_id}", ex=ttl, xx=True, get=True)
# old_value is None            -> unknown/expired/revoked
# old_value already "used:..." -> reuse detected -> mass-revoke
# old_value is "{user_id}"     -> legitimate first claim
```

Verified with the exact same concurrency test that caught the original SQL
race (`test_concurrent_rotation_of_the_same_token_only_lets_one_caller_win`,
8 threads hammering one token) — reran it 3 times in a row against the new
Redis-backed implementation to make sure it wasn't a fluke: exactly one
winner every time.

## Verified against real Redis, not just fakeredis

Same discipline as the Postgres migration — "SQLAlchemy/redis-py is
backend-agnostic" is a claim, not a guarantee, until it's actually run
against the real thing:

1. Started a real, throwaway Redis server (`redis-server --port 6390`,
   not the machine's default instance) and ran the entire 133-test suite
   against it via `REDIS_URL=redis://localhost:6390/0`.
2. Independently inspected the real Redis instance afterward —
   `redis-cli keys "*"` / `dbsize` — and found the actual keys the test
   run should have produced (`refresh:*`, `refresh_by_user:*`,
   `revoked:*`, 101 total), not an empty or suspiciously-fake-looking store.
3. Booted the full app (`uvicorn`) against a real Redis + fresh SQLite,
   and drove the complete flow with curl: register → refresh (200) →
   replay the old refresh token (401, rotation working) → logout (204) →
   reuse the just-revoked access token (`401 {"detail": "token has been
   revoked"}`) — every step against real infrastructure, not test doubles.

## What's still open (rest of Phase 01)

- Structured logging, Sentry, CI, Dockerfiles
- Rate limiting + OpenAPI enrichment
- The `redis` service in `docker-compose.yml` is provided but unverified
  in this sandbox specifically (no Docker available here) — same caveat
  as the `postgres` service; the underlying mechanism (redis-py + the
  atomic `SET ... XX GET` pattern) was verified directly against a real
  `redis-server` binary instead, which is the part that was actually in
  question.
- No connection-pool tuning or Redis Sentinel/cluster story — a single
  Redis instance is the whole design for now, same "bootstrap, not final"
  framing as everything else in this phase.
