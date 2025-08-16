# Phase 9c deep-dive: symptom photo upload

Third epic of the scale-up roadmap's Phase 05 (Reach & Polish). The
roadmap's own scope for this epic: "Secure image upload (e.g. a rash)
tied to a chat exchange, with provider-only review — scoped narrowly so
it stays a triage aid, not a diagnostic claim." That last clause set the
boundary for everything built here: nothing in this codebase looks at a
photo's *content* and draws a conclusion from it. No image classifier, no
ML model, no "this looks like X" — a photo is stored, and a human
(the patient, or a provider who can already see the record it's on)
looks at it. That's the entire feature.

## What "tied to a chat exchange" actually means here

The roadmap says "chat exchange," but this codebase has two separate
tables for a triage interaction: `ChatExchange` (a patient's own private
history, readable only by that patient — see
`docs/phase4c-chat-history.md`) and `TriageAuditRecord` (the
clinical/compliance audit trail, provider/admin-readable, panel-scoped —
see `docs/phase7a-patient-panels.md`). Only the second one has an
established, tested provider-visibility rule. Since the roadmap
explicitly wants "provider-only review," photos are attached to
`audit_record_id`, not `chat_exchange_id` — tying them to `ChatExchange`
would have made provider review impossible without inventing a new
visibility rule from scratch, when a correct one for exactly this
("can a provider see this artifact tied to this triage decision")
already exists and is already tested.

This did require one small, deliberate addition to the triage API
response: `/triage/intake` and `/triage/evaluate` now both include
`audit_record_id` in their JSON response (`app/api/triage.py`) — that id
didn't need to leave the backend before this epic (it was only used
internally, e.g. to link a high-risk alert to its triggering record).

## Validation: never trust what the client says about its own file

Two independent layers, in `app/services/symptom_photos.py`:

1. **A hard byte cap enforced while streaming the upload**
   (`app/api/symptom_photos.py`'s `_read_capped()`), not by trusting the
   `Content-Length` header — a client can lie about that, or omit it
   with chunked transfer encoding. The read is chunked (64 KiB at a
   time) and aborts with a 413 the moment the running total crosses
   `MAX_PHOTO_BYTES` (5 MiB by default), so a hostile oversized upload
   is never fully buffered into memory before being rejected.
2. **Pillow actually decodes and verifies the bytes** as one of three
   allowed formats (JPEG/PNG/WEBP) — `Image.verify()` catches truncated/
   corrupt files, and the resulting format is checked against a small
   allowlist rather than trusting the client's declared `Content-Type`
   or the filename's extension. A file renamed from `.php` to `.jpg`, or
   plain garbage, or a file with real JPEG magic bytes followed by
   garbage (tested explicitly), all get rejected with a 422 — not
   because of what the client claimed, but because of what the bytes
   actually decode to.

The on-disk filename is **always** server-generated — `uuid4().hex` plus
the extension Pillow itself determined from the decoded image, stored
under `UPLOAD_DIR/<audit_record_id>/<uuid>.<ext>`. `save_photo()` doesn't
even accept a client-supplied filename as a parameter, so there is no
path-traversal or overwrite surface to sanitize against — it's closed by
construction, not by a filter.

## A real bug caught by writing the test, not by inspection

Adding the upload endpoint should have been the end of it, but
`app/core/request_limits.py`'s `MaxBodySizeMiddleware` — added in the
API-hardening epic — caps every request body at 1 MiB, with a comment in
its own docstring that said, verbatim, "revisit if a file-upload endpoint
lands." One did. `MAX_PHOTO_BYTES` defaults to 5 MiB, so any real photo
upload over 1 MiB would have been rejected by this **unrelated**
middleware before ever reaching the new endpoint's own, larger,
purpose-built cap — a silent conflict between two correctly-written
pieces of code that individually made sense in isolation.

Caught by a test that deliberately generated a >1 MiB image (a solid-
color PNG compresses to a few KB regardless of dimensions — the test
uses seeded random noise pixels specifically so it doesn't compress away
the point it's testing) and asserting the upload succeeds, not just that
the middleware's own unit test doesn't 413 on `Content-Length`. Fixed by
exempting `POST .../photos` paths from the blanket 1 MiB cap in the
middleware — the endpoint still enforces its own cap via the same
streamed-read approach the middleware exists to protect against never
having, so the safety property (never buffer an unbounded body) is
preserved, just with the right limit for the right kind of request.
Both the middleware-level exemption and the full authenticated >1 MiB
upload are covered by dedicated regression tests.

## Visibility: reused, not reinvented

- **Upload** (`POST /audit/{id}/photos`): patient-only, and only onto a
  record where `record.patient_id == current_user.id`. An anonymous
  record (no patient attached) or another patient's record both 404 —
  same existence-hiding response shape used everywhere else in this
  codebase for "not yours to see," so a patient probing record ids can't
  distinguish "exists, not yours" from "doesn't exist."
- **List / view** (`GET /audit/{id}/photos`, `GET
  /audit/{id}/photos/{photo_id}`): the owning patient, or any provider/
  org_admin/admin who could already see that record via `GET
  /audit/recent` — reusing `app/services/patient_panel.py`'s
  `provider_can_view_record()` / `org_admin_can_view_record()` directly,
  the same functions `ClinicalNote` and `Referral` already share. A
  provider viewing photos is logged via `app/services/
  admin_action_log.py` (`viewed_symptom_photos`), same discipline as
  viewing clinical notes.
- **Delete** (`DELETE /audit/{id}/photos/{photo_id}`): patient-only,
  and only their own photo (checked against the photo's stored
  `patient_id`, not re-derived from the audit record) — a small
  self-service control so a patient who uploaded the wrong image isn't
  stuck with it, consistent with this project's general stance on
  patient data control (see `docs/phase8b-consent-and-data-rights.md`).
  Providers cannot delete a patient's photo — review-only, as the
  roadmap specifies.

## Frontend: authenticated images, not public URLs

A plain `<img src="...">` can't send an `Authorization` header, and every
other resource in this app requires one. `fetchSymptomPhotoBlobUrl()`
(`lib/api.ts`) fetches the image bytes with a bearer token, then hands
the browser a `blob:` object URL to actually render — `PhotoGallery.tsx`
revokes every URL it creates on unmount so they don't leak for the tab's
lifetime.

`PhotoGallery.tsx` is shared between two contexts via a `canManage` prop:
embedded in `TriageChat.tsx` under each freshly-completed triage result
(upload + view + delete, patient-owned), and in a new "Photos" column on
the provider `/audit` table (view-only, lazy-loaded per row on click —
fetching photos for all 50 rows up front on page load would be 50 extra
requests most rows never need).

## Live verification

Ran the real backend + frontend and drove it end to end:

1. `curl`-verified the full API flow first: registered a patient,
   submitted a triage, uploaded a real JPEG to the returned
   `audit_record_id`, confirmed the file landed on disk under
   `data/uploads/symptom_photos/<record_id>/<uuid>.jpg`, listed it back,
   and fetched the raw bytes — byte-identical to what was uploaded
   (`diff` on the two files matched exactly).
2. In the actual browser, logged in as a patient, submitted a real
   symptom message, and confirmed a "Photos" button appeared under the
   completed triage result exactly when (and only when) the response
   carried an `audit_record_id` — correctly absent for a `need_more_info`
   follow-up turn, since nothing is logged to the audit trail until a
   decision actually finalizes.
3. **A real, reproducible gotcha caught along the way**: the app's own
   service worker (from the PWA epic, `docs/phase9a-responsive-and-pwa.md`)
   was serving a *stale cached JS bundle* — new code changes were
   invisible in the browser even after a hard reload, because the
   service worker's cache-first strategy for the app shell served the
   old bundle instead of fetching the new one. Confirmed directly:
   fetching `/_next/static/chunks/app/page.js` returned code with none
   of this epic's new UI in it, while `navigator.serviceWorker.getRegistrations()`
   showed an active registration. Unregistering the service worker and
   clearing `CacheStorage` fixed it immediately. This isn't a code bug —
   it's a known, real interaction between the dev workflow and the PWA
   epic's own (deliberately cache-first) app-shell strategy, worth
   documenting explicitly for future work in this repo: **when testing
   fresh frontend changes against a dev server that has ever registered
   the service worker, unregister it and clear caches first**, or the
   browser will silently keep serving old code.
4. Uploaded a real photo via the API directly to the exact
   `audit_record_id` shown in the browser, then logged in through the
   real login form as a provider-panel admin and opened `/audit` —
   the "Photos" column's gallery for that exact record showed the real
   uploaded image (rendered as a `blob:` URL, confirmed via the DOM: one
   real `<img>` tag with a `blob:` source, and a screenshot showing the
   actual red test-image thumbnail), with no delete control (correctly
   read-only for a provider).

## What's still open

- **Photos aren't visible for exchanges loaded from `/triage/history`.**
  `ChatExchange` rows (what `/triage/history` returns) don't carry
  `audit_record_id` — there's no link between the two tables today — so
  after a page reload, only the CURRENT session's freshly-submitted
  results show a "Photos" control; older exchanges reloaded from history
  don't, even if photos exist for their underlying audit record. Fixing
  this would mean adding `audit_record_id` to `ChatExchange` (or another
  linking mechanism) and backfilling `GET /triage/history`'s response —
  a real gap, not addressed here to keep this epic's scope to what the
  roadmap actually asked for.
- **No re-fetch on toggle.** `PhotoGallery` loads once per mount (the
  first time it's expanded) and caches the result — collapsing and
  re-expanding within the same page view won't pick up a photo uploaded
  by someone else in the meantime (e.g. two browser tabs). A page reload
  always shows current state; live cross-tab sync does not exist.
- **No image compression/resizing.** A patient's phone photo is stored
  exactly as uploaded (up to the 5 MiB cap) — no thumbnail generation,
  no downscaling. Fine for a prototype; a real deployment serving many
  photos would want this for both storage cost and load time.
- **Local filesystem storage, not an object store.** `UPLOAD_DIR`
  (`app/core/config.py`) is a plain directory on disk — matches this
  project's zero-setup-by-default philosophy (same as the SQLite
  default), but doesn't work across multiple app instances/processes
  the way S3-or-equivalent would. A real multi-instance deployment would
  need to swap this for real object storage.
- **No frontend translation.** `PhotoGallery.tsx`'s UI strings
  ("Photos", "Hide photos", "No photos attached.") are English-only —
  not wired into `lib/i18n.ts` (see `docs/phase9b-internationalization.md`).
  A Spanish-language patient sees an English-labeled photo control.
