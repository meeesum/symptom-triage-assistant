# Phase 7a deep-dive: patient panels

First epic of the scale-up roadmap's Phase 03 (Provider & Care-Team
Platform) — closing the gap `app/api/audit.py`'s own docstring has
flagged since Phase 4b: "a provider currently sees every patient's
records, not just their own panel."

## What's built

- `app/models/patient_panel.py` — `PatientPanelAssignment`: a plain
  `(provider_id, patient_id)` pair with a unique constraint on that pair
  (a patient can have more than one provider; a provider can have more
  than one patient; the same pair can't be assigned twice). Admin-
  controlled, not self-service — the same pattern already established for
  role assignment (`app/api/admin.py`): a provider doesn't add patients to
  their own panel, an admin assigns them.
- `app/api/patient_panel.py` — `POST /panel/assignments` and
  `DELETE /panel/assignments/{id}` (admin-only), `GET /panel/assignments`
  (admin-only, every assignment), `GET /panel/mine` (provider/admin, only
  the calling provider's own panel).
- `TriageAuditRecord` gained a nullable `patient_id` column, populated
  from the logged-in patient's id when `/triage/intake` is called with a
  bearer token (still `NULL` for anonymous requests and for
  `/triage/evaluate`, which has no auth concept at all). This is the
  column `GET /audit/recent` now filters on for the `provider` role: only
  rows where `patient_id` is `NULL` (unattributable to anyone specific —
  stays visible to every provider regardless of panel, since restricting
  it further would only hide data, not protect anyone) or `patient_id` is
  one of that provider's panel patients. `admin` stays unrestricted — a
  strict superset, same relationship already documented for role.

## Verified live, not just tests

Ran the real dev server and drove the actual API with curl, using real
accounts (not mocked calls):

1. Created an admin directly in the DB, registered a provider and TWO
   separate patients (A and B) through the real registration endpoint.
2. Admin assigned patient A (only) to the provider's panel via
   `POST /panel/assignments`.
3. Patient B (NOT on the panel) submitted "sudden chest pain and
   sweating" → `cardiac_event_pattern`, emergency.
4. Patient A (ON the panel) submitted "facial drooping and slurred
   speech" → `stroke_fast_pattern`, emergency.
5. `GET /audit/recent` as the provider returned ONLY patient A's
   `stroke_fast_pattern` row — patient B's `cardiac_event_pattern` record
   was correctly absent.
6. The same query as admin returned BOTH rows, confirming admin's
   unrestricted view is unaffected by panel scoping.

This is the actual privacy boundary the epic exists to build, verified
end-to-end against a real running server and real distinct accounts, not
inferred from unit tests alone.

## Design choices worth calling out

- **`provider_id`/`patient_id` are plain `Integer`, not a SQLAlchemy
  `ForeignKey`** — matches every other cross-table reference in this
  codebase (e.g. `ChatExchange.user_id`). No FK constraint enforcement;
  pairing with an already-deleted user id is a theoretical gap the
  codebase accepts elsewhere too (there's no user-delete flow at all
  currently).
- **An audit row with no `patient_id` is visible to every provider,
  panel or not.** This is intentional, not an oversight: an anonymous
  triage request can't be tied to any patient in the first place, so
  scoping it further by panel wouldn't protect anyone's privacy — it
  would just make legitimate audit data invisible to everyone.
- **A provider with an empty panel sees only anonymous rows, not
  everything.** The naive alternative (empty panel → no filter → see
  everything) would silently un-scope a brand-new provider account
  before an admin gets around to assigning them any patients — the
  opposite of what this epic is for. Verified directly in
  `tests/test_audit_panel_scoping.py`.

## What's still open

- **Chat history (`app/services/chat_history.py`) is NOT panel-scoped.**
  It was already scoped to "the logged-in patient sees only their own
  history" before this epic, which is a different (and already correct)
  boundary — a provider was never able to read chat history at all, panel
  or not. Nothing to close here; noted so it's not mistaken for a gap.
- **No provider-facing UI for managing or viewing a panel** — this epic
  is backend-only, same scope decision as
  `docs/phase6e-clinical-review-workflow.md`. The existing `/audit`
  frontend page is unaffected code-wise (the backend does the filtering,
  the page just renders whatever it gets back) but doesn't yet show
  panel membership anywhere.
- **A provider can't request or self-manage their own panel** — fully
  admin-driven, matching the roadmap's own framing, but means an admin is
  a hard dependency for onboarding any provider-patient relationship. A
  self-service "request access to a patient's record with an audit trail
  of the request" flow is a reasonable future upgrade, not built here.
