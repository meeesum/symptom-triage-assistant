# Phase 7c deep-dive: referral & appointment tracking

Third epic of the scale-up roadmap's Phase 03 (Provider & Care-Team
Platform). Reuses patient panels' visibility rule (`docs/phase7a`), same
as clinical notes (`docs/phase7b`) — a referral is exactly as sensitive
as the audit record it's attached to.

## What's built

- `app/models/referral.py` — `Referral` (one per audit record, unique
  constraint on `audit_record_id` — this is "the case," not a log of
  repeated referral events) and `ReferralStatusChange` (append-only:
  every transition is recorded, nothing is ever overwritten — same
  "never overwrite, always append" instinct as `KbArticleSubmission`'s
  version history, applied to status instead of content).
- `app/api/referrals.py` — `POST /audit/{id}/referral` (create, starts at
  `referred`), `GET /audit/{id}/referral` (current status + full
  history), `PATCH /audit/{id}/referral` (advance status). All three
  gated to `provider`/`admin`, panel-scoped for `provider` exactly like
  clinical notes — an outsider provider gets 404, not 403 (see
  `docs/phase7b-clinical-notes.md` for why that distinction matters).

## Forward-only, but skipping is allowed

`advance_status()` enforces that a referral can only move to a status
LATER in `STATUS_ORDER = ("referred", "scheduled", "seen")` than its
current one — going backward, or "advancing" to the same status, is
rejected with a 409. But skipping an intermediate stage IS allowed: a
same-day walk-in can go straight from `referred` to `seen` without ever
passing through `scheduled`. This matters because real referral
workflows don't always go through every stage — forcing a provider to
record a fake "scheduled" step just to satisfy a state machine would be
friction for no real benefit, whereas allowing backward moves would let
someone quietly erase that a patient was already seen, which is exactly
the kind of history a clinical/compliance trail shouldn't allow.

## Verified live, not just tests

Ran the real dev server and drove the actual API with curl:

1. Created a referral for a real emergency-tier audit record —
   `status: "referred"`, one history entry.
2. Advanced it to `scheduled` — status updated, history now has two
   entries (`null → referred`, `referred → scheduled`).
3. Advanced it to `seen` — three history entries, correct order.
4. Attempted to move it back to `referred` — got a real `409` from the
   running server with the exact rejection message
   (`"cannot move referral from 'seen' to 'referred' — status can only
   move forward"`), not just an assertion in a mocked test.

## What's still open

- **No appointment date/time field** — "appointment tracking" in the
  roadmap's epic title is covered by the status transition itself
  (`scheduled`), not by an actual scheduled datetime. Adding a
  `scheduled_for: datetime` field (and maybe a reminder/notification tied
  to it — see the upcoming notifications epic) is a natural follow-up,
  not built here; the roadmap's own loc estimate for this epic (~900 loc)
  is status-tracking-sized, not a real appointments calendar.
- **No link from a referral back to which provider is actually
  following up** — `created_by` records who opened the referral, but
  if the case is later reassigned to a different provider on the same
  panel, nothing tracks that explicitly; `changed_by` on each status
  change is the closest signal, but it's implicit, not a real assignment
  field.
- **No frontend UI** — backend-only pass, same scope decision as every
  other Phase 03 epic so far.
- **A referral can't be cancelled/withdrawn** — only forward progress
  through the three real statuses. A referral opened by mistake, or a
  patient who cancels before being seen, has no explicit terminal state
  to record that; it would just sit at `referred` or `scheduled`
  indefinitely. Worth a fourth status (e.g. `cancelled`) if this becomes
  a real gap in practice — not guessed at here.
