import pytest

from app.rag.llm_client import AnthropicLLMClient
from app.rag.pipeline import generate_explanation
from app.safety.engine import RedFlagEngine
from app.safety.schemas import OnsetSpeed, Severity, SymptomInput


class _FakeAnthropicClient(AnthropicLLMClient):
    """Stands in for a real Anthropic call in tests — the `anthropic`
    package isn't installed in this dev environment, and even if it were,
    tests shouldn't depend on network/API keys. Subclasses AnthropicLLMClient
    (rather than duck-typing) specifically so `isinstance(llm,
    AnthropicLLMClient)` in pipeline.py still routes through the real
    LLM-path branch, including the groundedness check — the thing under
    test here."""

    def __init__(self, canned_text: str):
        self._canned_text = canned_text  # deliberately skip super().__init__()

    def generate(self, prompt: str) -> str:
        return self._canned_text


@pytest.fixture(scope="module")
def engine():
    return RedFlagEngine()


@pytest.mark.asyncio
async def test_self_care_symptom_gets_grounded_explanation_with_sources(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # force extractive fallback

    symptom = SymptomInput(
        symptom_ids=["cough", "sore_throat"],
        severity=Severity.MILD,
        onset=OnsetSpeed.SUDDEN,
    )
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.explanation  # not empty
    assert "Common Cold" in result.sources[0] or any("Cold" in s for s in result.sources)


@pytest.mark.asyncio
async def test_no_matching_context_falls_back_to_rule_guidance(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Nonsense free_text with no KB-matching vocabulary at all — a real
    # no-context case, unlike a plain symptom_id (which the knowledge base
    # now covers for every symptom — see docs/phase6b). Should not crash,
    # should return *something*.
    symptom = SymptomInput(
        symptom_ids=[], onset=OnsetSpeed.GRADUAL, free_text="xylophone quantum blockchain"
    )
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.explanation


@pytest.mark.asyncio
async def test_grounded_llm_output_is_used_as_is(engine, monkeypatch):
    # Reuses vocabulary from the cough/sore-throat article — should pass
    # the groundedness check and be returned verbatim.
    canned = (
        "A mild cough and sore throat that develop gradually without high "
        "fever are most commonly caused by a common cold or other mild "
        "viral illness, per Common Cold, Cough, and Sore Throat."
    )
    monkeypatch.setattr("app.rag.pipeline.get_llm_client", lambda: _FakeAnthropicClient(canned))

    symptom = SymptomInput(symptom_ids=["cough", "sore_throat"], severity=Severity.MILD)
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.explanation == canned
    assert result.generation_source == "llm_grounded"


@pytest.mark.asyncio
async def test_ungrounded_llm_output_is_rejected_and_falls_back(engine, monkeypatch):
    # Vocabulary entirely unrelated to the retrieved cough/cold context —
    # must be rejected rather than shown to the patient.
    ungrounded = "Quantum computing relies on superposition and entanglement principles."
    monkeypatch.setattr("app.rag.pipeline.get_llm_client", lambda: _FakeAnthropicClient(ungrounded))

    symptom = SymptomInput(symptom_ids=["cough", "sore_throat"], severity=Severity.MILD)
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.explanation != ungrounded
    assert result.generation_source == "llm_rejected_ungrounded"
    assert result.explanation  # fell back to extractive text, not empty


@pytest.mark.asyncio
async def test_weakly_relevant_chunks_are_filtered_out_of_sources(engine, monkeypatch):
    # Regression test for a real bug found while verifying the multi-turn
    # epic live: after the knowledge-base expansion epic grew the corpus,
    # a "mild cough, gradual onset" query pulled in the heavy-vaginal-
    # bleeding-during-pregnancy and joint-pain articles into the sources
    # list and the extractive explanation, purely on generic vocabulary
    # overlap ("mild", "gradually") — confusing and, for the pregnancy
    # article specifically, alarming to show a cough patient. See
    # app/rag/pipeline.py's _filter_to_relevant and docs/phase6c.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    symptom = SymptomInput(
        symptom_ids=["cough"], severity=Severity.MILD, onset=OnsetSpeed.GRADUAL
    )
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.sources == ["Common Cold, Cough, and Sore Throat"]
    assert "vaginal" not in result.explanation.lower()
    assert "joint pain" not in result.explanation.lower()


@pytest.mark.asyncio
async def test_empty_llm_output_is_rejected_and_falls_back(engine, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.get_llm_client", lambda: _FakeAnthropicClient(""))

    symptom = SymptomInput(symptom_ids=["cough", "sore_throat"], severity=Severity.MILD)
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.generation_source == "llm_rejected_ungrounded"
    assert result.explanation


@pytest.mark.asyncio
async def test_pipeline_uses_real_entailment_check_when_configured(engine, monkeypatch):
    # End-to-end wiring check: with GROUNDEDNESS_METHOD=llm, the pipeline
    # must actually consult app.rag.groundedness.get_entailment_checker()
    # (via is_grounded's default) rather than the lexical heuristic — a
    # lexically-overlapping-but-contradictory claim that the lexical
    # checker would accept should be rejected here, since the fake judge
    # says "no". See app/rag/groundedness.py's LLMEntailmentChecker.
    from tests.test_llm_entailment import _FakeLLMEntailmentChecker

    monkeypatch.setenv("GROUNDEDNESS_METHOD", "llm")
    monkeypatch.setattr(
        "app.rag.pipeline.is_grounded",
        lambda explanation, chunks: _FakeLLMEntailmentChecker("no").check(explanation, chunks),
    )

    contradictory = "Chest pain and sweating resolve on their own, no treatment needed."
    monkeypatch.setattr(
        "app.rag.pipeline.get_llm_client", lambda: _FakeAnthropicClient(contradictory)
    )

    symptom = SymptomInput(symptom_ids=["cough", "sore_throat"], severity=Severity.MILD)
    escalation = engine.evaluate(symptom)
    result = await generate_explanation(symptom, escalation)

    assert result.explanation != contradictory
    assert result.generation_source == "llm_rejected_ungrounded"
