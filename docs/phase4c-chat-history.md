# Phase 4 deep-dive: chat history persistence

## What's built

- `app/models/chat_exchange.py` — `ChatExchange`: one row per patient
  message + response (user_text, tier, guidance, matched_rule_id, sources,
  understood_symptom_ids/severity/onset, tied to `user_id`).
- `app/services/chat_history.py` — `save_exchange()` / `get_history()`.
- `app/api/deps.py` — new `get_optional_current_user`, factored out of
  `get_current_user` via a shared `_resolve_current_user()` helper so the
  two share validation logic instead of duplicating it. Resolves to `None`
  on any failure (missing/invalid/expired/revoked token) rather than
  raising — for routes that work for anyone but behave differently when
  the caller happens to be logged in.
- `app/api/triage.py` — `POST /triage/intake` now takes an *optional*
  bearer token. Anonymous requests behave exactly as before (no history,
  no behavior change). A logged-in patient's exchange is also saved.
  `GET /triage/history` (any authenticated user, not role-gated — see
  below) returns that user's own past exchanges, oldest first.
- `frontend/components/TriageChat.tsx` — loads history on mount if a
  token is present, and sends the token (when present) on every submit.
  Verified live in a real browser: sent a message while logged in, did a
  full page reload (not a client-side route change — the whole JS runtime
  restarted), and the message was still there, loaded via a real
  `GET /triage/history` network call, not React state surviving the
  reload. Confirmed the isolation guarantee too: `GET /triage/history`
  with no token returns `401 {"detail":"missing bearer token"}`.

## Why `GET /triage/history` uses `get_current_user`, not `require_role`

Every logged-in user — patient, provider, or admin — has their own chat
history that's theirs to read; there's no role-based restriction here,
just "is this your own data." Using `require_role("patient", "provider",
"admin")` would have looked more consistent with `/audit/recent`'s
pattern but is actually wrong: it silently excludes any future role that
isn't in that literal list, when the real requirement is just "logged in
at all." `get_current_user` says that directly.

## Why anonymous stays fully anonymous, not "session-based" persistence

The obvious alternative — persist history for anonymous users too, keyed
on some client-generated session id — was deliberately not built. It
would mean tracking patient-identifiable symptom conversations without an
account or consent step behind them, which is exactly the kind of thing
Phase 0's compliance scoping exists to prevent. Persistence only ever
happens for a caller who explicitly created an account.

## Known limitations (tracked, not hidden)

- No delete/export of a patient's own history yet — once saved, a patient
  has no way to remove or download their conversation history from the
  UI (deletable only by direct DB access today).
- `free_text` is stored in full here (unlike the audit trail's truncated
  `free_text_excerpt`) — same retention/encryption gap already flagged
  for `TriageAuditRecord`, now duplicated onto a second table. A real
  deployment needs one retention/encryption policy applied consistently
  across both, not decided per-table.
- History doesn't distinguish emergency/urgent (fast-path) exchanges from
  routine/self-care (RAG) ones in any special way — both are saved
  identically. This is probably fine (a patient should be able to see
  their emergency-tier conversations too) but hasn't been explicitly
  reviewed against the audit trail's separate retention story for
  requires_human_review cases.
