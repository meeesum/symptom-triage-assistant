# Phase 10c deep-dive: cross-phase contract tests

Third and final epic of the scale-up roadmap's Phase 06 (Quality at
Scale) — **completing Phase 06, and the entire six-phase scale-up plan.**
The roadmap's scope: "Integration tests specifically at the seams
between phases — org isolation under panels, retention jobs against real
consent records — where bugs hide when features built independently
start interacting."

Every other test file in this codebase verifies one feature, built in
one epic, in isolation. This epic deliberately does the opposite:
`tests/test_cross_phase_contracts.py` combines features from DIFFERENT
epics in one scenario, because that's exactly where two independently-
correct pieces of code can produce a wrong RESULT together — a bug
neither one would ever show testing it alone.

## Investigate first, write tests second

Before writing any test, a research pass read the actual current source
of five specific seams (data-rights deletion × symptom photos, retention
purge × symptom photos, retention purge × consent/data-rights records,
org isolation × every panel-scoped feature, reporting exports × org
isolation) and reported back facts, not guesses. That pass surfaced
**two real, serious bugs** before a single test was written.

## Bug 1: "delete my data" left every uploaded photo behind, forever

`app/services/data_rights.py`'s `delete_user_data()` — the GDPR/HIPAA
"right to be forgotten" flow — deletes chat history, unlinks audit
records, and anonymizes the account. It never touched `SymptomPhoto`
rows or the actual image files on disk at all. Symptom photo upload
(Phase 05) was built a full epic after data-rights (Phase 04) and was
never wired back into it.

This is not a cosmetic gap. A photo of a rash, an injury, or another
visible symptom is frequently MORE sensitive than the free-text
description already covered by deletion, and it's exactly the kind of
data a real "delete my data" request is legally meant to remove. Left
as found, a patient who exercised their deletion right would have every
photo they ever uploaded sitting on disk and in the DB, indefinitely,
with no way to know it hadn't actually been deleted.

**Fixed**: `delete_user_data()` now calls the new
`list_photos_for_patient()` / reuses `delete_photo()` (which removes
both the DB row and the on-disk file) for every photo the patient
uploaded, before the anonymization transaction — same category as chat
history in the function's own accounting, not an afterthought. The
deletion summary now reports the photo count deleted alongside chat
exchanges and audit records.

## Bug 2: retention purge orphaned photos when it purged their audit record

`app/services/retention.py`'s `purge_old_data()` hard-deletes aged-out
`TriageAuditRecord` rows. It never touched `SymptomPhoto` rows either —
and because `SymptomPhoto.audit_record_id` is a plain Integer (not a
SQLAlchemy ForeignKey, the same pattern used throughout this codebase
for cross-table references), nothing would even raise an error to catch
this. A purged audit record's photos became silent orphans: DB rows
pointing at an audit_record_id that no longer existed, and files on
disk that would never be cleaned up by anything, ever — a slow,
unbounded storage leak with no compliance benefit (the whole point of
retention is that data actually goes away).

**Fixed**: `purge_old_data()` now selects the ids of about-to-expire
audit records FIRST (in their own read, before the main delete
transaction — see the code comment for why this can't safely nest
inside the same transaction: `delete_photo()` opens and commits its own
session per photo, which risks a SQLite lock contending against the
outer, not-yet-committed transaction), deletes each one's photos via
the new `delete_photos_for_audit_record()`, and only then runs the bulk
audit-record delete. `RetentionPurgeRun` gained a new
`symptom_photos_deleted` column (with a real Alembic migration,
`server_default='0'` since the table already has real rows from every
prior epic's own verification) so a purge run's actual scope is fully
visible via `GET /admin/retention/runs`, not just implied.

## What retention correctly does NOT touch — locked in, not just assumed

The same investigation confirmed `purge_old_data()` never queries or
deletes `ConsentRecord` or `DataRequest` rows — exactly right, and
exactly what the roadmap's own "retention jobs against real consent
records" framing is checking for: a retention POLICY (aged-out data
nobody asked about) is a different concern from a compliance record of
what consent was given or what a specific deletion/export request did,
which must persist regardless of age for the audit trail's own
compliance purpose. `TestRetentionNeverTouchesComplianceRecords` locks
this in with two tests that backdate a `ConsentRecord` and a
`DataRequest` to 10 years old, run a real purge, and confirm both
survive untouched — a regression guard against someone "helpfully"
adding these tables to the purge scope later without realizing why they
were deliberately excluded.

## Org isolation, checked against every panel-scoped feature at once

`TestOrgIsolationAcrossPanelScopedFeatures` builds ONE real scenario —
two organizations, a provider and patient in org A (panel-assigned), an
outsider provider in org B, and a real emergency triage submitted
through the actual `/triage/intake` endpoint — then checks that the SAME
org boundary holds consistently across `GET /audit/recent`, `POST
/audit/{id}/notes`, `POST`/`GET /audit/{id}/referral`, and `GET
/audit/analytics`. The point isn't that any ONE of these was suspected
of leaking — each already has its own dedicated test file — it's that a
single shared scenario proves they all agree with each other, rather
than four independently-passing tests that could each individually be
right while still disagreeing about a case none of them individually
covers.

`TestReportingExportsRespectOrgIsolation` extends the same check to the
CSV export added in the reporting-exports epic (Phase 05), confirming
`build_audit_csv` genuinely excludes another org's record — parsed via
`csv.DictReader` and checked against the actual `id` column, not a raw
substring search (see "A real bug in the test itself," below, for why
that distinction mattered).

## A documented, currently-dormant risk — not fixed, on purpose

The same investigation found that org-boundary enforcement happens ONCE,
at `assign_patient()`'s write time (it rejects a cross-org
provider/patient pair) — but every downstream reader
(`audit_visibility_clause`'s provider branch, `analytics.py`, alerting's
recipient resolution) trusts the panel-assignment table without
re-checking `org_id` at read time. Today this is **unreachable**: no
endpoint anywhere in this codebase changes a `User.org_id` after
creation, only role. `TestStalePanelAssignmentAfterHypotheticalOrgChange`
documents this directly — it simulates the hypothetical at the DB layer
(there being no real endpoint to drive it through) and asserts the
CURRENT, dormant behavior explicitly, so that if an org-transfer feature
ever ships, this exact test starts failing — which is the point: a
future feature would need to either re-validate panel assignments on
org change, or re-check `org_id` at read time in the three places
listed above.

## A real bug in the test suite itself, caught by running it twice

The first version of `test_csv_export_excludes_other_orgs_records`
asserted `str(record_id) not in csv_bytes.decode("utf-8")` — a raw
substring search over the entire CSV blob. It passed in isolation but
**failed intermittently when run as part of the full 517-test suite** —
not because org isolation leaked anything, but because this test suite
shares one backend DB across all test files (deliberately, matching the
project's `tests/conftest.py` design), and a numeric record id can
coincidentally appear as a substring inside a completely unrelated row's
date, another row's id, or any digit-containing field created by a
different test file entirely. This is exactly the false-positive trap a
"grep the whole blob" assertion sets in a shared-DB test suite. Fixed by
parsing the CSV with `csv.DictReader` and checking the `id` COLUMN
specifically — re-ran the full suite three times consecutively after the
fix to confirm it was actually gone, not just not-reproduced-this-time.

## Live verification

Both real bugs were verified fixed against a real running server, not
just the test suite:

1. Registered a real patient, submitted a real triage, uploaded a real
   photo via the actual API, confirmed the file existed on disk, called
   `POST /data-rights/deletion` for real, and confirmed both the
   response ("1 symptom photo(s) deleted, ...") and the actual
   filesystem (the file was genuinely gone) agreed.
2. Created a real audit record backdated 400 days with a real attached
   photo, ran the real `scripts/run_retention_purge.py` (not a mocked
   call), and confirmed the file was genuinely gone from disk afterward.
   Also updated that script's own summary print and the
   `GET /admin/retention/runs` API response model to surface the new
   `symptom_photos_deleted` count — the CLI report and the admin-facing
   API were both still silently omitting it after the model gained the
   column, which would have been its own small honesty gap.

## Test coverage added

`tests/test_cross_phase_contracts.py` (13 tests): 4 org-isolation tests
across audit/notes/referrals/analytics, 1 reporting-export org-isolation
test, 2 retention-never-touches-compliance-records tests, 2 data-rights-
deletion-removes-photos tests, 3 retention-purge-removes-photos tests
(including the "recent records keep their photos" negative case — purge
must NOT delete photos for records still within the retention window),
and 1 documented-dormant-risk test for the stale-panel-assignment
scenario.

All 517 backend tests pass (504 pre-existing + 13 new), reverified
clean across three consecutive full-suite runs after the CSV-export
test fix; `ruff check` clean.

**This completes Phase 06 (Quality at Scale) — and the entire six-phase
scale-up plan.** All three Phase 06 epics (end-to-end Playwright suite,
expanded adversarial eval + load testing, cross-phase contract tests)
are done, tested, and documented.
