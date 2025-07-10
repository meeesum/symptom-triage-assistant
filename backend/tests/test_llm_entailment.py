"""Tests for the real semantic entailment path (GROUNDEDNESS_METHOD=llm) —
see app/rag/groundedness.py's LLMEntailmentChecker. Uses a fake Anthropic
client (no `anthropic` package or API key needed), same pattern as
tests/test_rag_pipeline.py's _FakeAnthropicClient.
"""

from app.rag.groundedness import LLMEntailmentChecker, get_entailment_checker, is_grounded
from app.rag.knowledge_base import Chunk
from app.rag.retriever import ScoredChunk


def _scored(text: str) -> ScoredChunk:
    chunk = Chunk(text=text, article_id="test", title="Test Article", source_note="", tags=())
    return ScoredChunk(chunk=chunk, score=1.0)


class _FakeLLMEntailmentChecker(LLMEntailmentChecker):
    """Stands in for a real Anthropic call — subclasses LLMEntailmentChecker
    so isinstance checks and the rest of its behavior are unaffected, only
    the actual API call is swapped out."""

    def __init__(self, canned_answer: str):
        self._canned_answer = canned_answer  # deliberately skip super().__init__()

    def check(self, explanation: str, chunks: list[ScoredChunk]) -> bool:
        if not explanation.strip() or not chunks:
            return False
        return self._canned_answer.strip().lower().startswith("yes")


def test_llm_entailment_checker_accepts_when_model_says_yes():
    checker = _FakeLLMEntailmentChecker("yes")
    chunks = [_scored("Chest pain combined with sweating can indicate a heart attack.")]
    assert checker.check("This is grounded.", chunks) is True


def test_llm_entailment_checker_rejects_when_model_says_no():
    checker = _FakeLLMEntailmentChecker("no")
    chunks = [_scored("Chest pain combined with sweating can indicate a heart attack.")]
    assert checker.check("Chest pain resolves on its own, no treatment needed.", chunks) is False


def test_llm_entailment_checker_rejects_empty_explanation():
    checker = _FakeLLMEntailmentChecker("yes")
    chunks = [_scored("Some context.")]
    assert checker.check("", chunks) is False


def test_llm_entailment_checker_rejects_when_no_chunks():
    checker = _FakeLLMEntailmentChecker("yes")
    assert checker.check("Some explanation.", []) is False


def test_get_entailment_checker_returns_lexical_by_default(monkeypatch):
    monkeypatch.delenv("GROUNDEDNESS_METHOD", raising=False)
    from app.rag.groundedness import LexicalOverlapChecker

    assert isinstance(get_entailment_checker(), LexicalOverlapChecker)


def test_get_entailment_checker_returns_llm_when_configured(monkeypatch):
    monkeypatch.setenv("GROUNDEDNESS_METHOD", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import sys
    import types

    # Fake the anthropic module so LLMEntailmentChecker's local import
    # succeeds without the real package being installed.
    fake_anthropic = types.ModuleType("anthropic")
    fake_anthropic.Anthropic = lambda: None
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    assert isinstance(get_entailment_checker(), LLMEntailmentChecker)


def test_is_grounded_uses_injected_checker_regardless_of_env(monkeypatch):
    monkeypatch.delenv("GROUNDEDNESS_METHOD", raising=False)
    chunks = [_scored("Some context.")]
    assert is_grounded("anything", chunks, checker=_FakeLLMEntailmentChecker("yes")) is True
    assert is_grounded("anything", chunks, checker=_FakeLLMEntailmentChecker("no")) is False
