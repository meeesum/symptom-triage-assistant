"""Dense retriever tests — run against the deterministic fake embedder
(EMBEDDING_FAKE=1, set by default in conftest.py) so they're fast and
offline, same as the rest of the suite. See test_dense_retriever_live.py
for the real fastembed + Qdrant path.
"""

from app.rag.dense_retriever import DenseRetriever
from app.rag.knowledge_base import load_chunks


def test_dense_retriever_ranks_relevant_article_first_for_chest_pain_query():
    # See the matching test in test_retriever.py for why this avoids
    # "shortness of breath" — that term now has its own dedicated article.
    # Kept short (unlike the TF-IDF version) because the fake embedder used
    # here is an unweighted bag-of-words hash with no stopword filtering —
    # filler words dilute the match more than they would for TF-IDF's
    # idf-weighted, stopword-filtered vectorizer.
    retriever = DenseRetriever(load_chunks())
    results = retriever.retrieve("chest pain", k=3)
    assert results, "expected at least one result"
    assert results[0].chunk.article_id == "chest_pain"


def test_dense_retriever_ranks_relevant_article_first_for_stroke_query():
    retriever = DenseRetriever(load_chunks())
    results = retriever.retrieve("facial drooping slurred speech", k=3)
    assert results[0].chunk.article_id == "stroke_warning_signs"


def test_dense_retriever_returns_nothing_for_empty_query():
    retriever = DenseRetriever(load_chunks())
    assert retriever.retrieve("", k=3) == []


def test_dense_retriever_respects_k():
    retriever = DenseRetriever(load_chunks())
    results = retriever.retrieve("fever headache pain", k=2, min_score=0.0)
    assert len(results) <= 2


def test_dense_retriever_rejects_empty_chunks():
    import pytest

    with pytest.raises(ValueError):
        DenseRetriever([])


def test_get_default_retriever_uses_dense_backend_when_configured(monkeypatch):
    from app.rag.retriever import get_default_retriever

    get_default_retriever.cache_clear()
    monkeypatch.setenv("RETRIEVAL_BACKEND", "dense")
    try:
        retriever = get_default_retriever()
        assert isinstance(retriever, DenseRetriever)
    finally:
        get_default_retriever.cache_clear()
