# Phase 2 deep-dive: the deterministic red-flag safety engine

## Why this exists before the LLM/RAG layer

The core risk in a symptom-triage product isn't "the LLM gives a mediocre
answer" — it's "the LLM under-calls the severity of something dangerous
because it hedges, gets talked out of it by user phrasing, or the retrieval
step pulls weak context." An LLM's failure mode on a health question is
usually confident-sounding and hard to catch by inspection.

So the highest-risk decisions — "is this an emergency" — are made by a
**deterministic rule engine that never touches the LLM**. `RedFlagEngine`
(`app/safety/engine.py`) is a pure function: structured symptom input in,
an escalation tier out. No network calls, no model calls, no randomness.
That means:

- It can be exhaustively unit tested (`tests/test_red_flag_engine.py`,
  20 cases covering every rule + edge cases like unknown severity and
  rule precedence).
- Its behavior is fully explainable — every decision cites the exact
  `matched_rule_id` that fired.
- A non-engineer (a clinical reviewer) can read and edit `rules.yaml`
  without touching Python.
- The LLM is only ever in the loop for `routine`/`self_care` tiers, where
  the cost of a so-so answer is low. `emergency`/`urgent` tiers short-circuit
  in `app/api/triage.py` before `generate_explanation()` is ever called.

## Design decisions worth knowing about

**Rules are data, not code.** `rules.yaml` is evaluated top-to-bottom,
first match wins, ordered emergency → urgent → routine → self_care. This
means a symptom combination (e.g. chest pain + sweating) can escalate past
what either symptom alone would trigger, simply by being listed earlier
with an `all_of`/`any_of` combination match.

**Unknown severity never satisfies a `severity_at_least` gate.** If we
don't know how severe something is, we don't treat that as "meets the
threshold" — see `_meets_severity()`. This is a deliberate fail-safe: it
means some symptoms may under-escalate without more info collected
upstream (a UX problem to solve in the intake flow), but the engine itself
never fabricates certainty it doesn't have.

**No rule ever silently resolves to self-care by default.** Any symptom
pattern the rule set has never seen falls through to a `routine` tier with
a generic "go get this checked" message (`_DEFAULT_UNMATCHED_GUIDANCE`),
never to "you're probably fine." See
`test_unclassified_symptom_never_defaults_to_self_care`.

**Age gates use fractional years**, not integer years — this was caught by
the test suite itself (`test_infant_fever_is_always_emergency_regardless_of_severity`
failed on first run because `age_years: int` rejected `0.1`). A 3-month-old
infant is `age_years=0.25`; integer-only ages would have silently made the
"any fever in an infant under 3 months is always emergency" rule
unreachable for real infant ages. This is exactly the kind of bug this
test suite exists to catch before it reaches a real user.

## What's explicitly NOT done yet (tracked for later phases)

- Rules are keyed on normalized `symptom_ids` (e.g. `"chest_pain"`), not
  raw text — the conversational intake layer that maps free text →
  `SymptomInput` doesn't exist yet. That's Phase 2 UI/NLU work.
- `app/rag/pipeline.py` is a stub that echoes rule guidance; real
  retrieval + generation lands once the Phase 1 knowledge base is ingested.
- `app/services/audit_log.py` logs to stdout only; Phase 4 wires this to a
  durable, queryable audit table.
- No red-teaming/adversarial eval pass yet (Phase 3) — the current test
  suite covers known rules correctly, not unknown attack surface like
  minimization phrasing ("it's probably nothing but...") or multi-symptom
  ambiguity outside the rules we've anticipated.
