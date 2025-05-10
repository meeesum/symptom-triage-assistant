# Phase 8b deep-dive: consent & data rights

Second epic of the scale-up roadmap's Phase 04 (Multi-Tenancy &
Compliance), closing the gap `docs/phase4c-chat-history.md` explicitly
flagged: "no consistent retention/encryption policy across chat history
and the audit trail's free-text fields."

## What's built

- `app/models/consent.py` — `ConsentRecord`: append-only, one row per
  consent DECISION (not per user) — withdrawing consent is a new row,
  not an update, so a compliance review can always answer "when did they
  withdraw, and what did they agree to before that." `CONSENT_TYPES` is
  a small, fixed set (`data_processing`, `marketing_communications`),
  each corresponding to an actual thing this product does with personal
  data, not a guess at future ones.
- `POST`/`GET /consent` — self-service, same pattern as notification
  preferences: a user records their own consent, no admin in the loop.
- `app/models/data_request.py` + `app/services/data_rights.py` — GDPR/
  HIPAA-style **export** (`POST /data-rights/export`) and **deletion**
  (`POST /data-rights/deletion`), both self-service and synchronous (not
  queued — a single user's own data is small and bounded; the job-queue-
  dependent epic in the roadmap is "Retention & purge jobs," a separate,
  later one).

## Export: complete, not capped

`GET /triage/history` caps at 200 rows for normal browsing (see
`app/services/chat_history.py`). The export deliberately does NOT reuse
that capped function — a GDPR "what do you have on me" request that
silently truncates at 200 would be a real compliance bug, not a
performance optimization. `export_user_data()` queries `ChatExchange`
directly, uncapped. Verified live: registered a real account, sent one
triage message, exported — the export contained exactly that one
exchange with its real content, not a placeholder.

## Deletion: anonymization, not a hard DELETE — and why

This is the one design decision in this epic worth explaining at length,
because a naive reading of "delete my data" would just `DELETE FROM
users WHERE id = ...`. That was deliberately NOT done:

- **Dozens of other tables reference a user's id with a plain `Integer`,
  not a SQLAlchemy `ForeignKey`** — `PatientPanelAssignment`,
  `ClinicalNote.author_id`, `Referral.created_by`,
  `KbArticleSubmission.submitted_by`, `Alert.recipient_provider_id`, and
  more (see `app/models/patient_panel.py`'s docstring for why this
  pattern exists throughout this codebase). A hard delete would silently
  orphan every one of those references — no constraint would even catch
  it — and would permanently destroy the ability to answer "who approved
  this KB article" or "who wrote this clinical note," which is exactly
  the kind of accountability a COMPLIANCE epic should be strengthening,
  not breaking.
- **GDPR itself explicitly allows this.** Article 17(3) permits retaining
  data past an erasure request when there's a legitimate reason — here,
  the audit trail's own compliance purpose (the same reason
  `TriageAuditRecord` exists in the first place). Anonymizing the
  identifying LINK while keeping the clinical/compliance event itself
  intact is a recognized approach, not a workaround.

So `delete_user_data()` does, precisely:
1. **Chat history is genuinely deleted.** `ChatExchange` rows are
   patient-authored free text about themselves with no compliance
   purpose independent of the patient — this is what "delete my chat
   history" (named directly in `docs/phase4c-chat-history.md`'s open
   items) means, and it's an actual `DELETE`, not a soft flag.
2. **Audit records are unlinked, not deleted.** `patient_id` is set to
   `NULL` — identical to what an anonymous triage request already looks
   like (see `docs/phase7a-patient-panels.md`). The clinical event stays
   in the audit trail; it can no longer be tied back to this person.
3. **Notification preferences are deleted outright** — nothing to
   anonymize, just a preference no one needs for an account that can't
   log in anymore.
4. **The account itself is scrambled**: email → an unrecoverable,
   unguessable `deleted-user-{id}-{random}@deleted.invalid`, password
   hash → a random value nobody has ever typed. Login becomes permanently
   impossible.
5. **Every refresh token is revoked immediately** (new
   `revoke_all_refresh_tokens_for_user()`, promoted from a private helper
   `rotate_refresh_token()`'s reuse-detection path already had), and the
   CURRENT access token is revoked too (the API layer has its `jti`) —
   an anonymized account must not stay usable via a token minted before
   the request for the rest of that token's remaining life.

## Verified live, not just tests — the full lifecycle

Ran the real dev server against a real registered account:

1. Submitted real consent (`data_processing: true`).
2. Submitted a real triage message ("I have a mild cough and sore
   throat").
3. `POST /data-rights/export` returned the exact real consent record and
   chat exchange, not placeholders.
4. `POST /data-rights/deletion` — succeeded.
5. Reused the SAME access token that had just performed the deletion →
   real `401 "token has been revoked"`.
6. Attempted login with the original (correct) email/password → real
   `401 "invalid email or password"` (the account's credentials no
   longer match anything).
7. Queried the DB directly: 0 remaining `ChatExchange` rows for that
   user, the `TriageAuditRecord` still exists but `patient_id` is `NULL`,
   and the `User.email` is a real anonymized placeholder
   (`deleted-user-1-f9bd9c2835bfd800@deleted.invalid`).

Every claim in the design section above was independently confirmed
against real database state and real HTTP responses, not asserted from
reading the code.

## What's still open

- **Encryption at rest is still not addressed** — this epic closes the
  "retention" half of the gap `docs/phase4c-chat-history.md` flagged, not
  the "encryption" half. Encrypting existing DB columns is invasive
  infrastructure work (key management, migration of existing plaintext
  data) genuinely out of scope for this pass, not glossed over.
- **Export doesn't include clinical notes or referrals written ABOUT the
  patient by a provider** — only data the patient themselves generated
  (chat, audit records tied to them) or explicitly agreed to (consent).
  A patient's right to see a provider's clinical impressions about them
  is a real, separate question this export doesn't answer yet.
- **No consent GATING anywhere** — `has_consented()` exists as a real,
  working function, but nothing in `/triage/intake` or elsewhere actually
  checks it before processing a request. Building the tracking mechanism
  and wiring it into product behavior were treated as separable; only
  the former is done here.
- **Deleting a provider/org_admin account doesn't clean up their panel
  assignments or reassign their patients** — `delete_user_data()` works
  identically regardless of role, but a deleted provider's existing
  `PatientPanelAssignment` rows are left pointing at their (now
  anonymized) id. A patient orphaned this way isn't reassigned to anyone.
- **No rate limiting on `/data-rights/export` or `/deletion`** — unlike
  `/auth/register`/`/login`, these aren't currently on the app's
  per-endpoint rate limiter, though they require a valid access token
  already (a real barrier the auth endpoints don't have).
