# Phase 7b deep-dive: clinical notes

Second epic of the scale-up roadmap's Phase 03 (Provider & Care-Team
Platform), depending on `docs/phase7a-patient-panels.md` — the panel
visibility rule this epic reuses rather than reinventing.

## What's built

- `app/models/clinical_note.py` — `ClinicalNote`: `audit_record_id`,
  `author_id`, `note_type` (`clinical_impression` / `follow_up` /
  `general` — the "structured" half of "free-text and structured
  annotations"), `body` (the free-text half), `created_at`. Plain
  `Integer` references, not SQLAlchemy `ForeignKey`s — same pattern as
  `PatientPanelAssignment` and every other cross-table reference in this
  codebase.
- `app/api/clinical_notes.py` — `POST /audit/{record_id}/notes`,
  `GET /audit/{record_id}/notes`, both gated to `provider`/`admin`.

## A note is exactly as sensitive as the record it's attached to

The core design decision here: clinical notes don't get their own
visibility rule. `_check_visible()` calls the exact same
`provider_can_view_record()` helper (new, in
`app/services/patient_panel.py`) that `GET /audit/recent`'s query filter
already encodes — a provider can read or add a note on a record if and
only if they could see that record via `/audit/recent` in the first
place (their panel, or an anonymous record with no `patient_id`). `admin`
stays unrestricted.

An outsider provider (not on the patient's panel) gets a **404**, not a
403 — deliberately indistinguishable from "no such record exists." A 403
would leak the fact that record N exists and belongs to someone outside
this provider's panel; a 404 doesn't. This is the same existence-hiding
judgment already applied elsewhere in this codebase (e.g. login's
identical error for "wrong password" vs. "no such user" — see
`docs/phase4b-auth-rbac.md`), extended to a new resource.

## Verified live, not just tests

Ran the real dev server and drove the actual API with curl:

1. Admin created a provider, a patient, and assigned the patient to the
   provider's panel.
2. Patient submitted "sudden chest pain and sweating" → emergency,
   `cardiac_event_pattern`.
3. Provider looked up the resulting audit record via
   `GET /audit/recent`, then added a `clinical_impression` note
   ("Called patient, advised immediate ER visit...") via
   `POST /audit/{id}/notes` — got back the note with the correct
   `author_id`.
4. `GET /audit/{id}/notes` returned it.
5. Created a SECOND, separate provider account NOT assigned to this
   patient's panel. `GET /audit/{id}/notes` as that provider returned
   **404** — confirmed live, not just asserted in a mocked test, that the
   panel boundary actually blocks a real, different account.

## What's still open

- **No note editing or deletion** — only create and list. A note, once
  added, is permanent; there's no correction mechanism if a provider
  makes a typo or wants to retract something. Given this is a clinical
  annotation trail, an audit-friendly "supersede, don't overwrite" edit
  model (a new note referencing/correcting an old one, rather than
  mutating it) would be the natural fit if this becomes a real gap —
  not built here.
- **No frontend UI** — backend-only pass, same scope decision as
  `docs/phase6e-clinical-review-workflow.md` and
  `docs/phase7a-patient-panels.md`.
- **`note_type` is a flat, fixed set of three strings**, not extensible
  per-deployment or validated against anything richer (e.g. structured
  fields per type, like a follow-up date for `follow_up` notes). Kept
  minimal since the roadmap's own loc estimate for this epic (~700 loc)
  is small — a richer structured-notes schema is a reasonable future
  upgrade once there's a real workflow need for it, not guessed at now.
- **A note's author isn't validated against still being the record's
  provider at read time** — if a panel assignment is later removed, a
  note the (formerly assigned) provider wrote stays visible only to
  providers *currently* on the panel (and admin), which is correct, but
  the note itself doesn't get any "author no longer has standing" marker.
