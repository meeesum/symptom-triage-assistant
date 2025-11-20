# Phase 8a deep-dive: organizations (multi-tenancy)

First epic of the scale-up roadmap's Phase 04 (Multi-Tenancy &
Compliance), depending on `docs/phase7a-patient-panels.md` — the panel
assignment model this epic's whole isolation strategy is built on top of.

## The core design decision: enforce isolation once, at assignment time

The roadmap epic asks for "tenant-scoped data isolation across every
existing table." A literal reading would add an `org_id` column to every
downstream table this project has built across Phase 02 and Phase 03 —
audit records, chat exchanges, KB submissions, clinical notes, referrals,
alerts, notification preferences — and re-check it on every single query.
That was deliberately NOT done. Instead:

- Every `User` belongs to exactly one `Organization` (`org_id`, embedded
  in the JWT alongside `role`, same trust model).
- `app/services/patient_panel.py`'s `assign_patient()` — the ONE place a
  provider ever gets linked to a patient — now rejects a cross-org pair
  outright (`CrossOrgAssignmentNotAllowed`, HTTP 422).
- Every downstream panel-scoped view built in Phase 03 (`GET
  /audit/recent`, clinical notes, referrals, analytics, alerts) already
  filters through `list_panel_patient_ids()`/`provider_can_view_record()`
  — and since a provider's panel can now never contain a patient outside
  their own org, tenant isolation for all four of those endpoints falls
  out for free, with no changes needed to any of them.

This is a real architectural bet: prevention at the one write path that
creates cross-user relationships, instead of detection scattered across
every read path that consumes them. It's also verifiable in a way a
scattered approach isn't — one test suite around `assign_patient()`
covers the invariant for every current and future panel-scoped view,
rather than needing a matching test for each one.

## What's built

- `app/models/organization.py` — `Organization` (id, name, unique slug).
- `app/models/user.py` — `org_id` (non-nullable), and a new `"org_admin"`
  role: a per-tenant superset of `"provider"` (user management + panel
  assignment, scoped to their own org). The pre-existing `"admin"` role
  becomes the platform-wide, cross-org role — reserved for
  `scripts/create_admin.py`-style bootstrap/support use, not everyday
  operation, now that `org_admin` covers normal per-tenant administration.
- `POST /organizations` — the actual "org signup/onboarding flow": one
  unauthenticated call creates a brand-new, isolated org AND its first
  `org_admin` account. This is what lets a SECOND organization onboard at
  all, without an existing platform admin in the loop. Rate-limited
  (5/min), same abuse-cost reasoning as `/auth/register`.
- `POST /auth/register` gained an optional `org_slug` — omit it to join
  the zero-setup `"default"` organization (seeded once by the migration
  itself, not lazily in application code — see that migration's own
  docstring for why), matching this codebase's established "every
  existing workflow keeps working unchanged" pattern. Every pre-existing
  test in this project's 300+-test suite still passes unmodified because
  of this default.
- `app/api/admin.py` — `GET /admin/users` and `PATCH
  /admin/users/{id}/role` both org-scoped for `org_admin` (list filtered
  to their org; PATCH checks the target user's org even though it takes
  an arbitrary id directly, not just whatever the list happened to show).
  An `org_admin` cannot grant the platform `"admin"` role — that would be
  an escalation out of their own tenant.
- **Existence-hiding, applied to a new resource.** An `org_admin` acting
  on a user outside their org gets a 404, not a 403 — same judgment
  already used for login errors and out-of-panel audit records: don't
  confirm a resource outside someone's boundary even exists.

## Verified live against a real running server, with two real tenants

1. Signed up two real organizations via `POST /organizations` (Acme
   Clinic, Beta Health), each with its own real `org_admin` account.
2. Registered a provider and a patient into Acme, a separate patient into
   Beta, via `POST /auth/register` with `org_slug`.
3. `GET /admin/users` as Acme's admin showed only Acme's 3 users; as
   Beta's admin, only Beta's 2. Confirmed with real, distinct accounts,
   not mocked.
4. Attempted a cross-org panel assignment (Acme's provider → Beta's
   patient) as Acme's org_admin — got a real `404` (Beta's patient is
   invisible to Acme's admin at all). Attempted the SAME assignment as
   the platform admin (who CAN see both orgs) — got the real `422` with
   the actual mismatch reason
   (`"provider 3 (org 2) and patient 5 (org 3) belong to different organizations"`),
   proving the rejection is enforced at the service layer regardless of
   who's asking, not just hidden by the API layer's visibility scoping.
5. Confirmed a legitimate same-org assignment still succeeds normally.

## What's still open

- **No frontend UI** for org signup, org-switching, or org-scoped admin
  views — backend-only pass, same scope decision as most of Phase 03's
  epics. `/auth/register`'s frontend form doesn't have an org_slug field
  yet.
- **Anonymous triage requests still have no org signal at all** — a
  `TriageAuditRecord` with `patient_id IS NULL` can't be attributed to
  any organization, same as it can't be attributed to any patient (see
  `docs/phase7a-patient-panels.md`). This is a legitimate, unavoidable
  consequence of anonymous triage staying anonymous, not a gap in the
  isolation logic.
- **A user's org membership is permanent** — no "move a user to a
  different org" operation exists. Given panel assignments are the
  enforcement point, moving a user between orgs without also
  untangling their existing panel assignments could leave a stale
  cross-org assignment sitting in the DB (created back when it was
  valid). Not a live bug (nothing currently allows changing `org_id`
  after creation), but worth flagging before ever adding that operation.
- **`org_admin` promoting another user to `org_admin` within their own
  org is allowed** — a deliberate choice (an org's own admin should be
  able to deputize another), but means a compromised `org_admin` account
  could mint more `org_admin` accounts in the same org. Bounded blast
  radius (still can't escalate to platform `admin` or reach another org),
  but worth knowing.
- **Consent & data rights, admin action audit log, and retention/purge
  jobs** — the other three epics in Phase 04 — are not built yet.
