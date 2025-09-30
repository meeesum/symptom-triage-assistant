"""Opt-in live test against the real fastembed model + in-memory Qdrant —
skipped by default because it downloads ~35MB from the HF Hub on first run
(~15s, network required). Not part of the default test run for the same
reason ANTHROPIC_API_KEY-gated tests aren't: this suite must stay fast and
offline by default (see tests/conftest.py).

Run explicitly with:
    RUN_LIVE_EMBEDDING_TESTS=1 EMBEDDING_FAKE= pytest tests/test_dense_retriever_live.py -q

Manually verified once while building this feature (see
docs/phase6a-dense-retrieval.md) — this test exists so that verification is
repeatable, not just a one-time claim.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_EMBEDDING_TESTS") != "1",
    reason="downloads a real model from the HF Hub — opt in with RUN_LIVE_EMBEDDING_TESTS=1",
)


def test_real_fastembed_ranks_chest_pain_article_first():
    from app.rag.dense_retriever import DenseRetriever
    from app.rag.embeddings import FastEmbedClient
    from app.rag.knowledge_base import load_chunks

    retriever = DenseRetriever(load_chunks(), embedding_client=FastEmbedClient())
    # Deliberately avoids breathing language — the knowledge base has a
    # dedicated cardiac_warning_signs article covering shortness of breath
    # (see docs/phase6b-knowledge-base-expansion.md), so a paraphrase that
    # mixes in breathing symptoms legitimately ranks that article instead.
    # This isolates the chest-pain paraphrase gap TF-IDF's own docstring
    # named as its limitation.
    results = retriever.retrieve("there's a squeezing pressure in the center of my chest", k=3)

    assert results, "expected at least one result"
    assert results[0].chunk.article_id == "chest_pain"
