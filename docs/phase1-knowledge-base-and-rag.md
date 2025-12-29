# Phase 1 deep-dive: knowledge base + retrieval + grounded generation

## What's built

- `data/knowledge_base/articles/*.json` — 6 seed articles (chest pain,
  stroke warning signs, fever, allergic reactions, common cold/cough,
  abdominal pain), each pre-chunked into paragraphs with `tags` linking
  back to the `rules.yaml` symptom IDs and rule IDs they support.
- `app/rag/knowledge_base.py` — loads and chunks articles, attaching
  provenance (`article_id`, `title`, `source_note`) to every chunk.
- `app/rag/retriever.py` — TF-IDF + cosine similarity retrieval index,
  exposed as `Retriever.retrieve(query, k) -> list[ScoredChunk]`.
- `app/rag/llm_client.py` — pluggable generation: real Anthropic call if
  `ANTHROPIC_API_KEY` is set, otherwise a deterministic extractive fallback
  that quotes the top retrieved chunks directly.
- `app/rag/pipeline.py` — wires retrieval + generation together;
  `generate_explanation()` is no longer a stub.
- `app/rag/groundedness.py` — a lexical overlap check run on real
  LLM-generated output (never on the extractive fallback, which is
  grounded by construction). See "Groundedness verification" below —
  this closes the item that used to be listed under "Explicit next steps"
  in this same doc.

## Why TF-IDF instead of dense embeddings, for now

Dense embeddings (sentence-transformers + a real vector DB like Qdrant)
are the intended production retrieval layer — that's still the plan in the
original roadmap. TF-IDF is a deliberate bootstrap choice for this stage:

- No model download, no vector DB service, no network dependency at query
  time — the whole pipeline runs and is testable in a plain `pip install`
  environment, which matters a lot while the knowledge base itself is
  still tiny and changing rapidly.
- The `Retriever` interface is shaped exactly like a dense-embedding
  retriever would be (`retrieve(query, k) -> list[ScoredChunk]`), so
  swapping the implementation later doesn't touch `pipeline.py` or any
  caller.
- **Known limitation, tracked on purpose**: TF-IDF is lexical, not
  semantic. `test_retriever_respects_min_score_threshold` documents that a
  query with no word overlap returns nothing — but the more dangerous
  failure mode is a *paraphrased* patient query ("my chest feels really
  tight and heavy") scoring low against `chest_pain` article text that
  says "chest pain" literally. This is the concrete reason dense
  embeddings are still the target for the real knowledge base once it's
  larger than 6 articles — TF-IDF will not scale semantically, only
  lexically.

## Why the LLM client is pluggable with a non-LLM fallback

This dev environment has no `ANTHROPIC_API_KEY` configured, and the
product should never be *undemoable* just because a key isn't present.
`ExtractiveFallbackClient` isn't a mock — it's a legitimate degraded mode:
it returns the actual verified knowledge-base text verbatim, with zero
risk of hallucination, because it never generates anything, only quotes.

This also sets up the eventual groundedness eval work (Phase 3): the
extractive fallback is effectively "ground truth" — any real LLM-generated
explanation should be checkable against how far it drifts from what the
extractive version would have said.

## Groundedness verification (follow-up pass)

`app/rag/groundedness.py::is_grounded()` runs only on the real
`AnthropicLLMClient` path (the extractive fallback quotes context verbatim
and needs no check). It's a lexical overlap heuristic — what fraction of
the generated explanation's distinct content words (4+ letters) also
appear in the retrieved context — not a semantic entailment check. That's
a deliberate, documented limit (see the module's docstring): it catches
the model drifting off into general knowledge instead of the retrieved
context, but it would NOT catch a fluent paraphrase that reverses the
actual clinical meaning while reusing the right vocabulary (e.g. "resolves
on its own" vs "requires emergency care" sharing most other words). A real
semantic/entailment check — an NLI model, or a second LLM call asking "is
this claim supported by this context" — is the intended production
upgrade once there's a real eval set to validate it against.

When the check fails (or the LLM returns empty text), `generate_explanation()`
discards the generated text entirely and falls back to the extractive
client's verbatim quote of the same retrieved chunks — the patient never
sees an ungrounded explanation, they see either a real grounded one or a
direct quote from the verified knowledge base. `RagGroundedExplanation`
now carries a `generation_source` field (`"extractive"` /
`"llm_grounded"` / `"llm_rejected_ungrounded"` / `"no_context"`) that's
threaded into the audit log (`decision_source` becomes e.g.
`"rag_pipeline:llm_grounded"`) — verified live end-to-end after wiring it
in.

Since this dev environment has no `anthropic` package installed (and no
`ANTHROPIC_API_KEY`), the LLM-path branch is tested with a fake subclass
of `AnthropicLLMClient` that returns canned text without making a network
call — see `tests/test_rag_pipeline.py`'s `_FakeAnthropicClient`. It
subclasses rather than duck-types specifically so `isinstance(llm,
AnthropicLLMClient)` in `pipeline.py` still routes through the real
LLM branch under test.

## Safety invariant preserved

Nothing about this phase changes the fast-path bypass in
`app/api/triage.py`: `generate_explanation()` is only ever called for
`routine`/`self_care` tiers. Verified live — see the emergency curl call
in the session log, which returns `"sources":[]` because the RAG pipeline
was never invoked for it.

## Explicit next steps (not done here)

- Real dense embeddings + persisted vector index once the KB grows past
  a handful of articles (TF-IDF rebuild-on-startup won't scale).
- A semantic/entailment-based groundedness check, once there's a real
  eval set to validate one against — the current lexical-overlap version
  is a documented interim step, not the final answer (see above).
- Expand the knowledge base to cover every `rules.yaml` rule (several
  urgent-tier rules — e.g. `moderate_breathing_difficulty`,
  `persistent_mild_symptoms` — don't have a matching article yet, so
  queries touching them currently fall back to bare rule guidance with no
  citations).
- Replace all `source_note: "PLACEHOLDER CONTENT"` articles with reviewed
  excerpts from an actual verified source before any real user sees this.
