# Phase 6a deep-dive: dense-embedding retrieval

First epic of the scale-up roadmap's Phase 02 (Clinical Depth). The
original TF-IDF retriever's own docstring named this the intended
production replacement — this closes that gap, without removing what it
replaces.

## What's built

- `app/rag/embeddings.py` — a pluggable `EmbeddingClient`, same shape as
  `app/rag/llm_client.py`'s pluggable LLM client:
  - `FastEmbedClient`: real embeddings via `fastembed`
    (`BAAI/bge-small-en-v1.5`, 384-dim, ONNX runtime). **Deliberately not
    `sentence-transformers`/torch** — `torch` has no distribution for this
    project's Python 3.13 in this environment (`pip install torch` fails
    with `ResolutionImpossible`/no matching distribution). `fastembed` is
    Qdrant's own embedding library and gives the same class of model
    without that dependency; verified live in this sandbox — model
    downloads (~15s, one-time, network required) and produces 384-dim
    vectors correctly.
  - `DeterministicFakeEmbeddingClient`: no model, no network, no
    torch/onnx — a stable hashed bag-of-words vector (word → index via
    md5 into a 1024-dim space, L2 normalized). Not a semantic embedding
    (can't relate "chest pain" to "cardiac discomfort"), but it preserves
    the one property the offline tests need: texts sharing words score
    higher than texts that don't, deterministically, in microseconds.
- `app/rag/dense_retriever.py` — `DenseRetriever`, implementing the exact
  same `retrieve(query, k, min_score) -> list[ScoredChunk]` interface as
  the existing TF-IDF `Retriever` (formalized as `RetrieverProtocol` in
  `app/rag/retriever.py`), so `app/rag/pipeline.py` never needs to know
  which one it's holding. Backed by `qdrant-client`:
  - **Local mode by default** (`QdrantClient(location=":memory:")`) — a
    real Qdrant engine running in-process, not a mock, the same "real
    implementation, just not networked" relationship fakeredis has to
    Redis.
  - **Real Qdrant server optional** via `QDRANT_URL` — same
    zero-setup-default / real-service-optional pattern as Postgres and
    Redis in Phase 01.
- `get_default_retriever()` in `app/rag/retriever.py` now switches on
  `RETRIEVAL_BACKEND`: `"tfidf"` (unset/default) keeps returning the
  original `Retriever`; `"dense"` returns a `DenseRetriever`. **TF-IDF
  stays the default** — dense retrieval is opt-in until it's had real
  pilot usage to validate against, matching the roadmap's own framing
  ("kept as a documented fallback rather than deleted outright").

## Why TF-IDF alone wasn't enough, verified concretely

The whole point of this epic, quoted from the TF-IDF retriever's own
docstring: it "will NOT generalize well to paraphrased or colloquial
patient language." Verified directly, not just asserted — the query
`"there's a squeezing pressure in the center of my chest"` (deliberately
zero lexical overlap with the `chest_pain` article's actual wording)
against the **real** `FastEmbedClient` + `DenseRetriever` still ranks the
`chest_pain` article first (see `tests/test_dense_retriever_live.py`).
The same query against TF-IDF would need to be re-verified per query
since TF-IDF is lexical by construction, but this is exactly the
paraphrase gap the roadmap named. (An earlier draft of this test used a
query mixing in breathing language — after the knowledge-base expansion
epic added a dedicated `cardiac_warning_signs` article covering shortness
of breath, that query legitimately started ranking that article instead;
see `docs/phase6b-knowledge-base-expansion.md`. Not a regression — a
consequence of there now being a more specific article to match.)

## Test strategy: fake by default, real path gated and verified

`tests/conftest.py` sets `EMBEDDING_FAKE=1` by default, same reasoning as
`REDIS_FAKE=1`: the real embedding client needs a one-time network model
download, and the test suite must stay fast and offline by default.
`tests/test_dense_retriever.py` and `tests/test_embeddings.py` run against
the deterministic fake and are part of the normal suite (152 passed
overall, up from 144, all offline). `tests/test_dense_retriever_live.py`
exercises the real `fastembed` model end-to-end and is skipped unless
`RUN_LIVE_EMBEDDING_TESTS=1` is set explicitly — run manually while
building this feature and passing, so the claim above is reproducible, not
a one-time verification that could silently rot.

Also verified: the full `generate_explanation()` pipeline
(`app/rag/pipeline.py`) actually works end-to-end with
`RETRIEVAL_BACKEND=dense` selected — not just the retriever in isolation.

## What's still open

- No reranking or query rewriting on top of the raw vector search — same
  scope limit the TF-IDF retriever already had ("intentionally still not
  smart," per `app/rag/pipeline.py`'s docstring).
- Not yet the actual default — needs real pilot triage transcripts to
  compare against TF-IDF before making the switch, not just this
  sandbox's synthetic queries.
- `fastembed`'s model choice (`BAAI/bge-small-en-v1.5`) isn't
  domain-tuned for clinical text; a medical-domain embedding model is a
  reasonable future upgrade once there's a labeled eval set to compare
  against (the adversarial eval harness from Phase 3 is the natural place
  to add that comparison).
- `QDRANT_URL`'s real-server path is implemented and follows the same
  pattern as `DATABASE_URL`/`REDIS_URL`, but — like the Postgres/Redis
  service containers in Phase 01's CI — has not been re-verified in this
  sandbox against an actual running Qdrant server (no Docker available
  here); only the in-memory local-mode path was exercised directly.
