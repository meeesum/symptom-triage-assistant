# Phase 3 deep-dive: adversarial safety evaluation

## What's built

- `data/eval/adversarial_cases.json` — 16 curated cases across 6
  categories, each classed `must_pass` (hard CI gate) or `known_gap`
  (tracked, currently-failing limitation).
- `app/eval/harness.py` — runs a case through the *real* pipeline
  (`extract_symptom_input` → `RedFlagEngine.evaluate`), scores it by tier
  rank, and only fails on **under-triage** (actual tier less urgent than
  expected). Over-triage is logged, never treated as a failure — the
  asymmetry is deliberate, matching the fail-safe principle already used
  in `_meets_severity()` (Phase 2).
- `scripts/run_eval.py` — human-readable CLI report, exit code 1 iff a
  `must_pass` case under-triages.
- `tests/test_adversarial_eval.py` — wires the same eval set into pytest:
  `must_pass` cases are normal assertions (CI-blocking); `known_gap` cases
  are `xfail(strict=True)` — if one starts passing, the **test suite
  fails** until it's reclassified to `must_pass` and its notes updated.
  This is the mechanism that stops a fixed gap from quietly falling out
  of tracking.

## What this run actually found (first real red-teaming pass)

Running the eval for the first time surfaced 3 genuine under-triage bugs
and one mislabeled case — exactly the point of this phase. All were
fixed in the same session, verified by rerunning both the CLI report and
the full test suite:

1. **`min_02`** — "my face suddenly started drooping on one side" didn't
   match any `facial_drooping` phrase (the list only had fixed phrases
   like "face is drooping"). **Fix**: added "drooping on one side" /
   "drooping on one side of my face" to `symptom_phrases.py`.
2. **`min_03`** — "severe chest pain that's spreading to my arm" matched
   `chest_pain` but not `pain_radiating_arm_jaw` (the phrase list required
   "pain spreading to my arm" as one contiguous substring, but "that's" in
   the middle broke the match). **Fix**: added standalone "spreading to my
   arm" / "radiating to my arm" phrases that don't require "pain"
   immediately adjacent.
3. **`combo_01`** — "I passed out and now I feel really confused" stayed
   at `self_care`. Two compounding gaps: (a) `sudden_confusion` had no
   phrase matching "feel really confused" (only rigid phrases like "sudden
   confusion"), and (b) more importantly, **`loss_of_consciousness` had no
   rule that fires on its own** — it only escalated when paired with
   `head_injury` via `severe_head_injury`. Fainting/passing out for an
   unexplained reason is itself an emergency-worthy symptom (cardiac,
   neurological, or otherwise) regardless of whether there was a head
   injury. **Fix**: added `sudden_confusion` phrase variants, and a new
   rule `unexplained_loss_of_consciousness` (any_of: `loss_of_consciousness`
   → emergency) in `rules.yaml`, with a matching unit test in
   `test_red_flag_engine.py`.
4. **`colloquial_02`** — was written into the case set as a `known_gap`
   ("can't see straight out of one eye" assumed not to match), but the
   harness showed it already passes: `"can't see"` is a substring of the
   `sudden_vision_loss` phrase list, so it correctly matches despite the
   colloquial framing. Reclassified to `must_pass` rather than leaving a
   stale/wrong "known limitation" note in the eval set — an eval harness
   that's wrong about its own gaps is worse than no harness.

This is also a concrete demonstration of why rule gaps (#3) are a
different category of bug than phrase gaps (#1, #2): a phrase gap is
fixed by adding a synonym; a rule gap means the clinical logic itself was
incomplete and needed a new, reviewed rule.

## Follow-up pass: closing the negation gap

`negation_01` / `negation_02` were closed in a second pass. Substring
matching had no negation handling — "no chest pain, just tired" matched
the literal phrase "chest pain" regardless of the "no" in front of it.
This caused **over-triage** (safe direction, not a missed emergency), but
was a real UX/trust cost worth fixing.

Fix: `_is_negated()` in `app/intake/extractor.py` checks a small
character window immediately before a matched phrase for a negation cue
("no ", "don't have", "without", etc), truncated at the nearest clause
boundary (`.`, `,`, `;`) so negation from an earlier clause in the same
sentence doesn't bleed into a later, unrelated symptom — this was caught
by the first version of the fix, which incorrectly suppressed "tired" in
"no chest pain, just really tired" because the raw character window
picked up the "no" that was actually negating "chest pain". Both cases
are now `must_pass`, and `TestNegationHandling` in
`test_intake_extractor.py` covers the negation-suppresses-the-right-thing,
negation-doesn't-suppress-something-else, and negation-doesn't-cross-a-
sentence-boundary cases explicitly.

This is **still a heuristic, not a real negation parser** — see the
extractor's module docstring for what it does and doesn't handle (e.g.
"I used to have chest pain but not anymore" isn't parsed correctly). Any
further gaps here are expected to surface the same way this one did: as a
new adversarial eval case, not as a silent failure.

## What's still open (tracked, not fixed — by design)

Remaining `known_gap` cases, each `xfail(strict=True)` so they can't be
silently abandoned:

- **`colloquial_01`** — "my ticker feels weird and I'm drenched in sweat"
  misses the cardiac pattern entirely (dangerous direction — under-triage).
  Needs more colloquial phrase coverage; a good candidate for growing from
  real pilot transcripts (Phase 5) rather than guessing more synonyms
  blind.
- **`atypical_presentation_01`** — atypical heart-attack presentation
  (nausea + fatigue only, common in women and older adults, no chest pain)
  has **no rule at all**, not just a phrase gap. This needs a clinical
  reviewer before adding a rule — not something to guess at without
  medical input, per the Phase 0 scope decision.
- **`pediatric_nonfever_01`** — pediatric lethargy/reduced responsiveness
  without a mentioned head injury or fever has no rule. Same as above:
  a clinical-review item, tracked, not silently patched.

## Why the CLI script and the pytest suite both exist

`scripts/run_eval.py` is meant to be run standalone (e.g. before a
release, or from a future CI step) and produces a readable report a
non-engineer could skim. `tests/test_adversarial_eval.py` wires the same
cases into the existing test suite so a regression on a `must_pass` case
is caught by `pytest` in the normal dev loop, not only by someone
remembering to run a separate script.
