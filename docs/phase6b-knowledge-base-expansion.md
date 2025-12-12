# Phase 6b deep-dive: knowledge-base expansion

Second epic of the scale-up roadmap's Phase 02 (Clinical Depth), alongside
`docs/phase6a-dense-retrieval.md`.

## What's built

- `scripts/kb_ingest.py` — an ingestion CLI with two subcommands:
  - `check-coverage`: cross-references every `symptom_id` referenced in
    `app/safety/rules.yaml` (via `app.safety.engine.load_rules()`, not a
    re-parse) against every KB article's `tags`, and reports which
    symptom_ids fall through to bare rule guidance with no supporting
    citation. This is the actual gap the roadmap named this epic to close.
  - `add`: ingests a draft article from a simple frontmatter+body text
    file (see `scripts/drafts/*.txt` for the eleven used to build this
    epic), validates required fields (`id`, `title`, `tags`,
    `source_note`, at least one body paragraph) and id uniqueness, then
    writes a JSON article into `data/knowledge_base/articles/` with
    provenance stamped automatically.
- `app/rag/knowledge_base.py`'s `Chunk` dataclass gained three provenance
  fields: `reviewed` (bool, defaults `False`), `added_date` (defaults
  `None`), `source_type` (defaults `"placeholder"`) — populated from the
  article JSON with backward-compatible defaults so the original six
  articles (authored before these fields existed) still load unchanged.
  `reviewed` stays `False` for everything today, including the new
  articles — there is no reviewer queue yet to have approved anything
  (that's the Clinical Review Workflow epic still to come); the field
  exists now so it's already in place for that queue to populate later
  rather than requiring another schema migration then.
- **Eleven new KB articles**, closing all nineteen previously-uncited
  `symptom_id`s: `cardiac_warning_signs`, `severe_breathing_signs`,
  `severe_bleeding`, `suicidal_thoughts_self_harm`,
  `heavy_vaginal_bleeding_pregnancy`, `head_injury`,
  `loss_of_consciousness_fainting`, `headache_general`, `joint_pain`,
  `rash`, `localized_swelling_redness`. Verified directly:
  `python scripts/kb_ingest.py check-coverage` now reports "Every
  symptom_id in rules.yaml has at least one citing KB article" (exit 0),
  down from 19 uncovered before this epic — and this check now has its
  own test (`tests/test_kb_ingest.py`) so the claim stays enforced, not
  just true at the moment this was written.

## Eleven articles, not "40+" — a deliberate count, not a shortfall

The roadmap's loc estimate for this epic implied "40+ new articles." What
actually got built is eleven. This is a considered choice, not a
shortcoming against the budget: the epic's stated goal is "closing every
symptom in rules.yaml that currently falls back to bare rule guidance
with no citation," and eleven articles fully achieves that — every one of
the nineteen uncovered symptom_ids now has a citation. Related symptoms
that clinically cluster together (e.g. the four associated symptoms of a
heart attack — shortness of breath, sweating, nausea, radiating pain —
that only matter together as a *pattern*, per `cardiac_event_pattern` in
rules.yaml) are covered by one coherent article rather than four thin,
overlapping ones. Padding to a round number by splitting these back apart
would add files without adding real coverage, the same "don't add
abstractions beyond what the task requires" judgment this project applies
elsewhere. Further, finer-grained decomposition remains a legitimate
future direction once there's a labeled eval set (the adversarial harness
from Phase 3) to check whether finer granularity actually improves
retrieval quality, rather than guessing that it would.

## Still explicitly placeholder content

Every article, old and new, still carries `"source_type": "placeholder"`
and the same honest `source_note` disclaimer as the original six: this is
prototype-authored content, not excerpts from a licensed/verified medical
source. Broadening coverage does not change that — "Real (non-placeholder)
knowledge-base content, reviewed against an actual verified source"
remains explicitly listed as NOT implemented in the top-level README. The
`reviewed` field this epic added exists specifically so that distinction
(placeholder vs. actually reviewed) is a real, queryable fact about each
article going forward, not something that has to be inferred from
`source_note` text.

## A real ranking side effect, caught by the existing test suite

Adding `cardiac_warning_signs` (covering "shortness of breath") changed
which article a query combining "chest pain" and "shortness of breath"
ranks first — it now legitimately matches the new, more specific article
instead of the general `chest_pain` one. This broke
`test_retriever_ranks_relevant_article_first_for_chest_pain_query` (and
its dense-retriever and live-fastembed equivalents), caught immediately
by running the suite after ingesting the new articles. Fixed by narrowing
each test's query to isolate what it's actually testing (chest pain
alone) rather than loosening the assertion — the new ranking behavior is
correct, not a bug, and the tests should reflect what each one is
actually meant to verify. See the updated tests in
`tests/test_retriever.py`, `tests/test_dense_retriever.py`, and
`tests/test_dense_retriever_live.py`.

## What's still open

- No clinical reviewer has actually reviewed any of this content — see
  above. The two rule gaps already tracked in the README (atypical
  heart-attack presentation, pediatric lethargy) are unrelated to this
  epic's citation-coverage work and remain open.
- `check-coverage` verifies every symptom_id has *a* citation, not that
  the citation is good — it can't detect a thin or low-quality article,
  only a missing one. Content quality still depends on the (currently
  placeholder) authoring itself.
- The ingestion CLI's draft format is intentionally minimal (flat
  frontmatter + blank-line-separated paragraphs) — no support yet for
  updating an existing article in place, only adding new ones.
