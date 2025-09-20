# Phase 10b deep-dive: expanded adversarial eval + load testing

Second epic of the scale-up roadmap's Phase 06 (Quality at Scale). The
roadmap's scope: "Grow the 16-case adversarial set toward 100+, and add
load-testing scripts (Locust) against the new job-queue and rate-limiting
layers," depending on multi-turn triage and API hardening (both already
built — Phases 02 and 01).

## The eval set grew 16 → 72, and found 8 real bugs along the way

This was never meant to be "write 84 more cases to hit a round number."
Every candidate case was run for real against the actual extractor +
safety engine before being classified — the same discipline
`docs/phase3-adversarial-eval.md` established for the original 16 — and
several genuinely surprised the system. **8 real, safety-relevant bugs**
were found and fixed in the process, on top of the eval-set expansion
itself:

1. **Infant age stated in weeks wasn't parsed at all.** "my baby is 10
   weeks old and has a fever" fell all the way through to the
   unclassified `routine` fallback instead of `infant_high_fever`
   (emergency) — `_extract_age_years()` only recognized "year(s)/
   month(s) old" phrasing. This is arguably the single most safety-
   relevant fix in this whole pass: infant fever under 3 months is the
   textbook "always escalate" case, and it was silently missing the
   single most common way a parent actually states a newborn's age.
2. **"feels warm" wasn't a recognized fever phrase** — only "fever",
   "feverish", "running a temperature", "feels hot" were. Fixed
   alongside #1; both together mean "my newborn, 6 weeks old, feels
   warm" now correctly escalates.
3. **Patient context flags had ZERO negation awareness.** Unlike
   `symptom_ids`, `is_pregnant`/`is_immunocompromised`/
   `has_cardiac_history`/`has_respiratory_history` were matched with
   plain substring checks — "I'm not pregnant, just have a headache"
   incorrectly set `is_pregnant=True`. Over-triage direction (safe), but
   a real correctness/trust bug: telling a clearly-not-pregnant patient
   their symptoms need evaluation "because of the pregnancy" undermines
   trust in every other piece of guidance shown. Fixed by extracting the
   negation-aware scanning logic `_match_symptom_ids` already used into
   a shared `_any_phrase_affirmed()` helper, now used by both.
4. **A stroke sign phrased as "won't move right" instead of "drooping"
   matched nothing.** "one side of my face won't move right" returned
   `routine` instead of `emergency` — fixed by adding that phrasing to
   `facial_drooping`.
5. **"coughing up a lot of blood" matched nothing** — only the bare
   "coughing up blood"/"coughing blood" were recognized;
   `coughing_up_large_blood` now also catches the qualified phrasing a
   real patient is more likely to actually type.
6. **The canonical "worst headache of my life" phrasing didn't register
   as severe.** Only the bare substring "the worst" was a severe-severity
   phrase, and "worst one I've ever had" / "worst headache of my life"
   don't contain it — so `severe_headache_red_flag` (the rule that exists
   specifically for subarachnoid-hemorrhage-pattern headaches) never
   fired for the single most common way that pattern is actually
   described clinically.
7. **"chest discomfort" / "discomfort in my chest" — a common clinical
   framing for angina — matched no chest_pain phrase at all**, nor did
   "throat feels tight" match `throat_swelling` (a real anaphylaxis
   sign), nor "excruciating pain in my abdomen" match
   `severe_abdominal_pain` (which required the word "stomach" or "belly"
   specifically). All three fixed.
8. **Bare "fatigue" (without the "-d") wasn't a `mild_fatigue` phrase** —
   only "fatigued" was, so "slight fatigue today" matched no symptom at
   all.

All 8 fixes are simple, targeted phrase/logic additions (or, for #3, a
real refactor extracting shared negation logic) — the same
low-risk-fix-plus-full-regression-check discipline every prior epic in
this codebase has used. Full backend suite (517 tests) reverified clean
after each change, not just at the end.

## A harness bug fixed before it could hide more mislabeled cases

`avoid_overtriage`-category cases (guards against alarm fatigue — "an
isolated mild symptom must not spuriously escalate") were checked with
the same "must not under-triage" assertion every other case used. Since
`expected_tier="self_care"` is already the LOWEST tier rank, that
assertion could never actually fail no matter how badly the system
over-reacted — the check was structurally toothless. Concretely: the
pre-existing `over_triage_guard_02` case ("just a runny nose today,
feeling otherwise fine") had silently been resolving to `routine`, not
the `self_care` its own `expected_tier` claimed, since before this pass
— the old assertion simply never noticed, because `routine` still isn't
"under" `self_care`.

Fixed by adding an optional `max_tier` field (a real ceiling, checked via
a new `over_triaged` property) — used specifically by `avoid_overtriage`
cases, where over-escalation IS the failure mode being tested, while
every other category keeps the original "only under-triage is a
failure" asymmetry (over-triage in the safe direction is still logged,
never a failure, for the cases where that's the actual intent). Every
existing `avoid_overtriage` case's `expected_tier`/`max_tier` was
corrected to match the system's real, verified behavior rather than a
stale, never-actually-checked claim — an eval harness that's wrong about
its own gaps is worse than no harness, the same principle
`docs/phase3-adversarial-eval.md` already established.

## What's still open (16 known_gap cases, all `xfail(strict=True)`)

Grouped by root cause, not just listed:

- **Genuinely no fuzzy/typo matching** (by design — see extractor.py's
  module docstring): `ches pian and shortnes of breth` matches nothing.
- **Clinical jargon has no lay-language mapping**: dyspnea/diaphoresis/
  precordial pain, facial paresis/dysarthria, hematemesis/melena all
  match nothing — the extractor is lay-language-only by design, a hard
  boundary, not a phrase-list gap to patch with a jargon dictionary
  (which would blur the "deterministic, fully auditable" property the
  design trades for).
- **Symptoms/context with no symptom_id or rule at all yet** (a rules.yaml
  SCOPE decision, not a phrase gap — needs a clinical reviewer, same
  posture the original `atypical_presentation_01`/`pediatric_nonfever_01`
  already established): diarrhea/GI symptoms, presyncope ("feel like I'm
  gonna pass out"), palpitations ("heart feels like it's racing"),
  cardiac-idiom framing ("an elephant sitting on my chest").
- **`has_cardiac_history` is extracted but consulted by NO rule at all**
  — a patient with a known cardiac history presenting with recurring
  chest pressure arguably warrants more than `chest_pain_isolated`
  (urgent) alone suggests, but the right threshold needs a clinical
  reviewer's judgment, not a guess.
- **Spanish-specific negation asymmetry**: "no" is Spanish's primary
  negation particle and appears pervasively in common hedging idioms
  ("probablemente no sea nada" = "probably nothing") in a way the
  equivalent English idiom doesn't — this trips the shared negation-
  window heuristic in a way the identical English case doesn't. Real,
  language-specific, not fixed under this pass (a rewrite of the
  heuristic deserves its own careful pass, not a rushed change alongside
  dozens of other cases).
- **Spanish age phrasing isn't parsed** (already documented in
  `docs/phase9b-internationalization.md`'s "What's still open" — this
  pass adds a concrete, currently-failing case demonstrating it, rather
  than leaving it as an abstract note).
- **Severity word-boundary collision**: "extremely" contains the
  substring "extreme" (a severe-severity phrase), so "extremely MILD"
  misreads as severe. No live safety consequence found in the case that
  demonstrates it (no symptom_id matches "discomfort in my stomach"
  either, so the tier is `routine` regardless of the severity mislabel),
  but a real, honestly-tracked collision risk for a symptom whose rule
  DOES gate on severity — narrowing "extreme" to a word-boundary-safe
  form risks its own regressions and deserves its own pass.

## Load testing (Locust)

Two independent `scripts/loadtest/*.py` files, each targeting exactly
one of the roadmap's two named layers:

- **`locustfile_triage.py`** — a realistic mix of self-care (weight 5,
  the RAG-pipeline-heavy path) and emergency (weight 1, the fast-path +
  job-queue-enqueue path) triage submissions, anonymous (no auth), with
  1-3s think-time between messages to approximate real patient pacing
  rather than a tight hammer. Validates not just HTTP status but the
  actual returned `tier` for emergency messages — a correctness
  regression under concurrent load (e.g. a race in the safety engine)
  would fail here even if every request still returned `200`.
- **`locustfile_auth_rate_limits.py`** — deliberately its own file, no
  think-time, hammering `/auth/register` and `/auth/login` as fast as
  possible. What "passing" means here is the opposite of usual: BOTH
  some `200`s (real traffic within the limit isn't wrongly blocked) AND
  some real `429`s (the limiter is actually engaging under genuine
  concurrent pressure, not just a serial curl loop where timing never
  contends) — a run where every request silently succeeded would mean
  the limiter stopped working under concurrency, which the existing
  single-threaded rate-limiting pytest suite has no way to catch.

### Live verification (both run for real, not just written)

1. **Triage load test**: 10 simulated users, 20s, against a real running
   server with a real Redis (not fakeredis) — 98 requests, **0
   failures**, every emergency-tier response correctly tiered
   `emergency`. Confirmed the job-queue layer was genuinely exercised,
   not just the HTTP layer: `redis-cli LLEN rq:queue:high_risk_alerts`
   showed exactly 18 queued jobs, matching the 18 emergency requests
   sent.
2. **Auth rate-limit load test**: 20 simulated users, no think-time, 20s
   — **10,212 requests**, 0 unexpected failures. The custom verdict
   handler reported "register: 5 succeeded, 5104 got 429" — exactly the
   `/auth/register` 5/minute limit, holding under genuinely concurrent
   pressure orders of magnitude beyond what the existing single-threaded
   pytest suite could ever exercise.

## What's still open

- **No CI wiring** for either the expanded eval set (already ran via
  `pytest`, so it WAS already CI-gated before this pass — this just adds
  more cases to what's already gated) or the Locust load tests (which
  are, correctly, NOT meant to run on every commit — see each
  locustfile's own usage docs for the deliberate manual/ad-hoc trigger
  model).
- **Eval set is at 72, not literally 100+.** An honest count, not a
  padded one: every case here was individually run and verified for
  real, several catching genuine bugs along the way — quality over
  hitting a round number. Growing further toward 100+ is real,
  available future work, not abandoned.
- **Load tests are local-only** — both assume `127.0.0.1` (the rate-limit
  test specifically depends on every simulated user sharing one source
  IP, which only local Locust-against-localhost guarantees) and haven't
  been run against a real multi-instance deployment.
