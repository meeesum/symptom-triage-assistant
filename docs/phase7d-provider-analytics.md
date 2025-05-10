# Phase 7d deep-dive: provider analytics dashboard

Fourth epic of the scale-up roadmap's Phase 03 (Provider & Care-Team
Platform) — "the first real charts in the product," per the roadmap's
own framing, which is why this is the first Phase 03 epic that also
ships a frontend page, unlike the three purely-backend passes before it
(patient panels, clinical notes, referral tracking).

## What's built

- `app/services/audit_visibility.py` — the panel-based visibility rule
  (`docs/phase7a-patient-panels.md`) extracted from `GET /audit/recent`
  into a shared, reusable clause. `app/api/audit.py` was refactored to
  use it (no behavior change — same tests pass unchanged) specifically
  so this epic's analytics queries apply the EXACT same rule rather than
  a second, independently-maintained copy that could quietly drift from
  it.
- `app/services/analytics.py` + `GET /audit/analytics` — three
  aggregations, all read-only (no new tables):
  - `triage_volume_by_day` — one entry per calendar day in the window,
    zero-filled for days with no triages, so a chart doesn't need to
    fill gaps itself.
  - `tier_distribution` — counts per `EscalationTier`.
  - `time_to_follow_up_stats` — mean/median hours between an audit
    record's creation and the FIRST referral status change past
    `referred` (i.e. the first real follow-up action — `scheduled` or
    `seen`, whichever came first, since a referral can skip straight to
    `seen`). Records with no referral, or one still stuck at `referred`,
    aren't counted as zero — there's no follow-up to measure yet.
- `frontend/app/analytics/page.tsx` — stat tiles (total volume,
  avg/median follow-up time, referrals followed up on), an inline-SVG
  bar chart for daily volume, and a CSS bar chart for tier distribution
  reusing the existing tier color tokens. No chart library — this
  project's frontend has none, and the shapes needed here don't warrant
  adding one.

## Verified live, not just tests

Ran the real dev server (backend + `npm run dev` frontend) and drove the
actual browser:

1. Seeded 5 real triage decisions via the API (2 emergency, 1 urgent, 2
   self-care) and confirmed `GET /audit/analytics` returned exactly that
   distribution via curl first.
2. Logged in as a real admin account through the actual login form.
3. Navigated to `/analytics` — the stat tiles, volume chart, and tier
   distribution bars rendered with the exact same numbers curl had
   already confirmed (2/1/0/2), not a coincidence but the same data path.
4. Checked the browser console — no errors.

## A stale doc caught and fixed along the way

`frontend/app/audit/page.tsx`'s disclaimer still read "no per-provider
record scoping yet, any provider/admin account sees every patient's
records" — true when it was written, false since
`docs/phase7a-patient-panels.md` shipped two epics ago. Caught while
touching this page's sibling; fixed to describe the actual current
scoping and updated the `NavBar` to link to the new page.

## What's still open

- **`time_to_follow_up` only covers cases with a referral.** A record
  that never got a referral opened at all isn't part of the denominator,
  so this metric answers "how fast do we follow up once we decide to,"
  not "what fraction of cases get followed up on in the first place" —
  a different, and arguably more important, metric this doesn't compute.
- **No date-range picker in the UI** — the backend endpoint accepts
  `days` (clamped 1–365), but the frontend hardcodes 30. Wiring a
  control up is a small follow-up, not built here since the roadmap's
  loc estimate for this epic (~1,100) is chart-and-endpoint-sized, not a
  full BI tool.
- **No caching** — every page load re-runs the full aggregation queries
  against the DB. Fine at this data scale; would need revisiting before
  a deployment with a real volume of historical records.
- **The volume chart's SVG has no axis labels or hover tooltips beyond
  the native `<title>` element** (a browser-native tooltip on hover) —
  minimal by design for a first pass, not a finished charting component.
