# Phase 8c deep-dive: admin action audit log

Third epic of the scale-up roadmap's Phase 04 (Multi-Tenancy &
Compliance) — "a second, narrower audit trail than the clinical one,
covering the platform's own admins," per the roadmap's own framing.

## What's built

- `app/models/admin_action_log.py` — `AdminActionLog`: append-only, one
  row per action (actor, role, org, action type, target, structured
  detail). Same "never overwrite, always append" instinct as
  `ConsentRecord` and `ReferralStatusChange` — a log that could be edited
  after the fact isn't a log.
- `app/services/admin_action_log.py` — `log_admin_action()`, wrapped in
  try/except and logged at ERROR on failure rather than propagating,
  same principle as `app/services/audit_log.py`'s
  `log_triage_decision()`: a logging outage must never be able to block
  the actual action (a role change, a KB approval) it's recording.
- `GET /admin/action-log` — read-only oversight, org-scoped for
  `org_admin` (mirrors `GET /panel/assignments`'s scoping), unrestricted
  for platform `admin`.
- **Six action types wired into the real endpoints that do them**,
  covering both of the roadmap's own named examples:
  - `role_change` — `PATCH /admin/users/{id}/role`
  - `panel_assign` / `panel_unassign` — `POST`/`DELETE /panel/assignments`
  - `org_created` — `POST /organizations`
  - `kb_submission_approved` / `kb_submission_rejected` —
    `POST /kb-review/submissions/{id}/approve` / `/reject`
  - `viewed_clinical_notes` / `viewed_referral` — `GET
    /audit/{id}/notes` and `GET /audit/{id}/referral` — this is the
    roadmap's other named example, "who viewed which patient record,
    when," and it's genuinely an access log, not just a write log: it
    fires on a READ, the same way a real HIPAA access log would.

## Verified live, not just tests

Ran the real dev server:

1. Promoted a real user from `patient` to `provider` via
   `PATCH /admin/users/{id}/role` — `GET /admin/action-log` showed a real
   `role_change` entry with `{"from_role": "patient", "to_role":
   "provider"}`.
2. A real patient submitted an emergency triage. An admin then called
   `GET /audit/{id}/notes` on that specific record (no notes existed yet
   — the point was exercising the READ path, not creating one) — the
   action log immediately showed `viewed_clinical_notes` against that
   exact `audit_record` id, most-recent-first alongside the earlier role
   change.

## A real gap this epic surfaced, not fixed here

While wiring `org_admin` into this epic's logging, it became clear that
**`org_admin` is missing from `require_role(...)` on six existing
Phase 03 endpoints** — `GET /audit/recent`, `GET /audit/analytics`,
`GET /alerts/recent`, both clinical-notes routes, all three referral
routes, and `GET /panel/mine` all still gate on `require_role("provider",
"admin")` only, from before `org_admin` existed
(`docs/phase8a-organizations.md`). `app/models/user.py`'s own docstring
describes `org_admin` as "a strict superset within their own org:
everything a provider can do, plus..." — but today an `org_admin`
account gets a flat 403 on all six of these, because they were never
updated when the role was introduced.

This is a **fail-closed** bug (over-restrictive, not a data leak — no
`org_admin` can see anything they shouldn't; they just can't see things
they should be able to), not fixed in this pass: doing it properly needs
`app/services/audit_visibility.py`'s clause extended with a real
`org_admin` branch (scoped to their whole org's patients, not just a
provider's own panel), not just adding the role string to
`require_role(...)`, which would currently fall through to "no
restriction at all" for that role — a correctness gap of its own if done
carelessly. Flagged explicitly here rather than silently worked around,
since fixing it is real, scoped work of its own.

## What's still open

- **The six-endpoint `org_admin` access gap above.**
- **No action types for consent/data-rights events** — `POST
  /data-rights/deletion` and `/export` already get their own dedicated
  log (`DataRequest`, see `docs/phase8b-consent-and-data-rights.md`), so
  this wasn't duplicated here; worth a second look if the two logs ever
  need to be correlated in one place for a real compliance review.
- **No retention policy for this log itself** — an audit log that grows
  forever without a retention policy is itself a data-hygiene question;
  the next epic (Retention & purge jobs) is where that would apply, not
  addressed here.
- **`detail` is an unstructured JSON blob**, not validated per
  `action` type — reasonable for a first pass (six action types, each
  hand-written), but wouldn't scale cleanly to many more action types
  without per-action schemas.
- **No frontend UI** — backend-only pass, same scope decision as most of
  this project's admin/compliance-facing epics.
