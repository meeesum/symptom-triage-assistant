# Phase 6d deep-dive: semantic groundedness check

Fourth epic of the scale-up roadmap's Phase 02 (Clinical Depth), following
`docs/phase6a-dense-retrieval.md`, `docs/phase6b-knowledge-base-expansion.md`,
and `docs/phase6c-multi-turn-triage.md`.

## What's built

`app/rag/groundedness.py`'s `is_grounded()` — called only on the real
Anthropic LLM path (the extractive fallback quotes context verbatim and
is grounded by construction) — now supports two pluggable checkers, same
pattern as `LLMClient` and `EmbeddingClient` elsewhere in `app/rag/`:

- `LexicalOverlapChecker` (**default, unchanged**): the original word-
  overlap heuristic, kept verbatim as `groundedness_score()`. Free,
  offline, deterministic.
- `LLMEntailmentChecker` (**new, opt-in via `GROUNDEDNESS_METHOD=llm`**):
  a second Anthropic call asking directly "does this claim follow from
  this context?" — a genuine semantic entailment check, not a fancier
  similarity metric. This is what the old module docstring named as the
  "intended production upgrade," now actually built.

## Why an LLM judge, not embedding similarity

The obvious "semantic, not lexical" upgrade already sitting in this
codebase is `app/rag/embeddings.py`'s dense embeddings from
`docs/phase6a-dense-retrieval.md` — cosine similarity between the
explanation and the context. That was deliberately NOT used here.
Generic sentence embeddings are good at topic similarity, not at telling
a *supported* claim from a topically-similar *contradiction* of it: "chest
pain resolves on its own, no treatment needed" and "chest pain combined
with sweating can indicate a heart attack" are about the same topic, in
similar vocabulary, and would likely still score reasonably close on
embedding cosine similarity — the exact failure mode this epic exists to
catch. An LLM asked directly "does the claim follow from the context, yes
or no" is answering the actual question, not a proxy for it. A real NLI
cross-encoder model would be a further, more specialized upgrade, but
those need `torch`, which — as already established in
`docs/phase6a-dense-retrieval.md` — has no distribution for this
project's Python 3.13 in this environment.

## Why opt-in, not the new default

`is_grounded()` runs on every real-LLM-path triage response. Making the
default itself another paid, network-dependent Anthropic call would mean
every triage request that reaches the LLM path now makes two API calls
instead of one, doubling latency and cost on the hot path, by default,
without the deploying team having decided that tradeoff is worth it. The
lexical heuristic remains free and instant; a deployment that wants the
stronger check opts in explicitly via `GROUNDEDNESS_METHOD=llm`, the same
"opt-in, don't change the default cost/latency profile" judgment already
applied to `RETRIEVAL_BACKEND=dense` and `allow_follow_up`.

## Test strategy: fakes for wiring, real call unverified in this sandbox

Same constraint as the rest of the LLM-path testing in this project: no
real `ANTHROPIC_API_KEY` is available in this sandbox, so the real
network call itself is unverified here — consistent with
`AnthropicLLMClient`'s own status throughout this codebase (see
`docs/phase1-knowledge-base-and-rag.md`). What IS verified:

- `tests/test_llm_entailment.py` — `_FakeLLMEntailmentChecker` subclasses
  `LLMEntailmentChecker` (skipping `__init__`'s real `anthropic.Anthropic()`
  construction, same pattern as `test_rag_pipeline.py`'s
  `_FakeAnthropicClient`) and returns a canned yes/no, verifying the
  checker's own accept/reject logic and its empty-explanation/no-context
  guards.
- `test_get_entailment_checker_returns_llm_when_configured` — fakes the
  `anthropic` module itself in `sys.modules` (the real package isn't
  installed in this dev environment) to prove `GROUNDEDNESS_METHOD=llm`
  actually resolves to `LLMEntailmentChecker`, not just that the class
  exists.
- `test_pipeline_uses_real_entailment_check_when_configured` (in
  `tests/test_rag_pipeline.py`) — the actual end-to-end wiring check: a
  lexically-overlapping-but-contradictory claim that the default lexical
  checker would ACCEPT is correctly REJECTED when
  `GROUNDEDNESS_METHOD=llm` is set and the fake judge says "no",
  confirming the pipeline really consults the configured checker rather
  than always falling back to the lexical one.

All 8 new tests pass; the full suite (187 passing, up from 179) passed
unchanged, confirming the default (lexical) path's behavior is untouched.

## What's still open

- The real LLM entailment call itself has not been exercised against the
  live Anthropic API in this sandbox — no API key is configured here (see
  above). The prompt template (`ENTAILMENT_PROMPT_TEMPLATE`) is
  straightforward but unvalidated against real model output at scale;
  a real deployment enabling `GROUNDEDNESS_METHOD=llm` should spot-check
  its actual yes/no judgments before relying on it.
- `LLMEntailmentChecker.check()` parses the response as "starts with
  yes" — a model that answers with any hedging or explanation instead of
  the requested single word would be treated as "no" (fails closed,
  which is the safe default for a rejection check, but means a verbose
  model response silently looks like a rejection rather than a parsing
  error).
- No cost/latency guard (e.g. a cache, or skipping the check for
  short/simple explanations) — every real-LLM-path response with this
  mode enabled makes a second full API call, at whatever the configured
  model's cost and latency are.
