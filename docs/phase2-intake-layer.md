# Phase 2 deep-dive: conversational intake layer

## What's built

- `app/intake/symptom_phrases.py` — the phrase dictionary: symptom_id →
  trigger phrases, plus severity/onset/context phrase maps.
- `app/intake/extractor.py` — `extract_symptom_input(text) -> SymptomInput`,
  pure substring matching + regex age parsing (handles both "3 month old"
  and "5 year old" phrasing, converting months to fractional years).
- `app/api/triage.py` — new `POST /triage/intake` endpoint (raw text in),
  sharing the same `_run_triage()` decision logic as `/triage/evaluate`
  (structured input in). Returns an `understood_*` block alongside the
  triage result.

## Why keyword matching, not an LLM, for extraction

This is the one place in the system where it would be easiest to reach for
an LLM (free text → structured JSON is a textbook LLM task) — and the one
place that's deliberately avoided here.

The safety engine's guarantees only hold for what it actually receives.
If extraction is done by a generative model, a missed or reworded symptom
never reaches `RedFlagEngine` at all, and that failure would be silent —
no error, no crash, just a normal-looking response that quietly skipped
the emergency rule. A keyword miss has the same effect, but it's the kind
of miss that shows up deterministically in a test (`test_every_rule_symptom_id_has_phrases`
enforces that every rule symptom has phrase coverage) and can be grown by
adding phrases, rather than depending on model behavior that can drift
between prompt versions or providers.

The `understood_symptom_ids`/`understood_severity`/`understood_onset`
fields returned by `/triage/intake` exist specifically so a future chat UI
can show the patient "here's what I heard" and let them correct it —
transparency as a mitigation for the extractor's recall limits, rather
than hiding them.

## Known limitation (tracked, matches the pattern from Phase 1 retrieval)

Substring matching only catches phrasing already in `symptom_phrases.py`.
"my chest feels like there's an elephant sitting on it" won't match
`chest_pain` today. Two ways to close this gap, in order of how much
they preserve the safety guarantee above:

1. **Grow the phrase list** from real user transcripts once there's usage
   data (Phase 5 pilot) — the standard, low-risk way to improve recall.
2. **LLM-assisted phrase *suggestion*, human-reviewed before merging** —
   an LLM proposes new candidate phrases from missed transcripts, a person
   adds them to `symptom_phrases.py`. This keeps the LLM out of the
   real-time safety path entirely; it only ever influences the *next*
   version of a reviewed, tested phrase list.

What this project will not do: put an LLM directly in the extraction path
for the tier decision. That tradeoff is explicit, not an oversight.

## Safety invariant preserved

`/triage/intake` calls the exact same `_run_triage()` function as
`/triage/evaluate` — there is no separate, less-tested code path for the
text-based entry point. Verified via
`test_intake_from_raw_text_escalates_correctly` and live curl calls
(cardiac sentence, infant-fever sentence, and self-care sentence all
routed correctly end-to-end).
