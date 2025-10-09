from app.rag.knowledge_base import load_chunks
from app.rag.retriever import Retriever


def test_load_chunks_finds_all_articles():
    chunks = load_chunks()
    article_ids = {c.article_id for c in chunks}
    assert "chest_pain" in article_ids
    assert "stroke_warning_signs" in article_ids
    assert "fever_general" in article_ids
    assert len(chunks) >= 10  # 6 articles x ~3 paragraphs each


def test_retriever_ranks_relevant_article_first_for_chest_pain_query():
    # Deliberately excludes "shortness of breath" — the knowledge base now
    # has a dedicated cardiac_warning_signs article for that term (see
    # docs/phase6b-knowledge-base-expansion.md), so a query combining both
    # terms legitimately ranks it first instead of the general chest_pain
    # article. This query isolates what it's actually testing.
    retriever = Retriever(load_chunks())
    results = retriever.retrieve("chest pain that won't go away", k=3)
    assert results, "expected at least one result"
    assert results[0].chunk.article_id == "chest_pain"


def test_retriever_ranks_relevant_article_first_for_stroke_query():
    retriever = Retriever(load_chunks())
    results = retriever.retrieve("facial drooping slurred speech", k=3)
    assert results[0].chunk.article_id == "stroke_warning_signs"


def test_retriever_returns_nothing_for_empty_query():
    retriever = Retriever(load_chunks())
    assert retriever.retrieve("", k=3) == []


def test_retriever_respects_min_score_threshold():
    retriever = Retriever(load_chunks())
    # a query with essentially no lexical overlap with the corpus
    results = retriever.retrieve("xylophone quantum blockchain", k=3)
    assert results == []


def test_get_default_retriever_is_singleton():
    from app.rag.retriever import get_default_retriever

    a = get_default_retriever()
    b = get_default_retriever()
    assert a is b
