"""Service-layer tests for the i18n epic's RAG/knowledge-base half:
per-language chunk loading, per-language retriever caching, and the
language-aware no-context fallback + prompt instruction.
"""

from app.rag.knowledge_base import load_chunks
from app.rag.llm_client import build_grounded_prompt
from app.rag.pipeline import _NO_CONTEXT_FALLBACK
from app.rag.retriever import Retriever, get_default_retriever


def test_load_chunks_no_filter_includes_both_languages():
    chunks = load_chunks()
    languages = {c.language for c in chunks}
    assert languages == {"en", "es"}


def test_load_chunks_filtered_to_english_excludes_spanish_articles():
    chunks = load_chunks(language="en")
    assert all(c.language == "en" for c in chunks)


def test_load_chunks_filtered_to_spanish_is_a_proper_subset():
    en_chunks = load_chunks(language="en")
    es_chunks = load_chunks(language="es")
    assert all(c.language == "es" for c in es_chunks)
    # Documented partial coverage (11 of 18 English articles) — not full
    # parity. See docs/phase9b-internationalization.md.
    assert len({c.article_id for c in es_chunks}) < len({c.article_id for c in en_chunks})


def test_spanish_retriever_ranks_chest_pain_article_first():
    # Deliberately avoids terms cardiac_warning_signs_es also repeats
    # heavily ("dolor", "pecho") — see test_retriever.py's equivalent
    # English test for the same reasoning.
    retriever = Retriever(load_chunks(language="es"), language="es")
    results = retriever.retrieve("opresión en el pecho por distensión muscular", k=3)
    assert results
    assert results[0].chunk.article_id == "chest_pain_es"


def test_get_default_retriever_caches_per_language():
    en_a = get_default_retriever(language="en")
    en_b = get_default_retriever(language="en")
    es_a = get_default_retriever(language="es")
    assert en_a is en_b
    assert en_a is not es_a


def test_no_context_fallback_has_english_and_spanish():
    assert set(_NO_CONTEXT_FALLBACK.keys()) == {"en", "es"}
    assert _NO_CONTEXT_FALLBACK["en"] != _NO_CONTEXT_FALLBACK["es"]


def test_grounded_prompt_instructs_spanish_response():
    prompt_en = build_grounded_prompt(["chest_pain"], "guidance", [], language="en")
    prompt_es = build_grounded_prompt(["chest_pain"], "guidance", [], language="es")
    assert "Spanish" not in prompt_en
    assert "Write your entire response in Spanish." in prompt_es
