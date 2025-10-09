"""RAG grounding pipeline.

Only called for `routine`/`self_care` tiers — see app/api/triage.py. The
emergency/urgent fast path never reaches this module, by design (see
docs/phase2-safety-engine.md).

Flow:
  1. Build a retrieval query from the patient's symptom_ids + free_text
  2. Retrieve top-k chunks from the local knowledge base (app/rag/retriever.py)
  3. Generate a grounded explanation:
       - real LLM call if ANTHROPIC_API_KEY is configured
       - deterministic extractive fallback otherwise (see llm_client.py)
  4. For the real LLM path only: run a groundedness check (see
     app/rag/groundedness.py) against the retrieved context. A generated
     explanation that fails the check is discarded in favor of the
     extractive fallback — never shown to the patient, never silently
     accepted. The extractive fallback is skipped for this check because
     it quotes context verbatim and is grounded by construction.
  5. Return the explanation plus the source titles used, for citation
     display in the frontend, plus whether it was LLM-generated-and-passed
     or fell back (extractive_client, no-context, or failed-groundedness)

This is intentionally still not "smart" — no reranking, no query
rewriting. The groundedness check defaults to a documented lexical
heuristic, but can opt into a real LLM-based entailment check via
GROUNDEDNESS_METHOD=llm — see app/rag/groundedness.py's module docstring
and docs/phase6d-semantic-groundedness.md for why that's opt-in, not the
default.
"""

from __future__ import annotations

from app.rag.groundedness import is_grounded
from app.rag.llm_client import (
    AnthropicLLMClient,
    ExtractiveFallbackClient,
    build_grounded_prompt,
    get_llm_client,
)
from app.rag.retriever import RetrieverProtocol, ScoredChunk, get_default_retriever
from app.safety.schemas import EscalationResult, SymptomInput

_NO_CONTEXT_FALLBACK = {
    "en": (
        "We don't have specific verified information on this combination of "
        "symptoms yet. Please use the guidance above, and reach out to a "
        "healthcare provider if you have any concerns."
    ),
    "es": (
        "Todavía no tenemos información verificada específica sobre esta "
        "combinación de síntomas. Por favor, sigue la orientación anterior y "
        "comunícate con un proveedor de salud si tienes alguna inquietud."
    ),
}

# A retrieved chunk must score at least this fraction of the TOP chunk's
# score to be treated as relevant enough to cite/generate from. Added
# after the knowledge-base expansion epic (docs/phase6b) made this
# concretely visible: retriever.retrieve()'s absolute min_score alone let
# through chunks that only share generic vocabulary with the query (e.g.
# a "mild cough, gradual onset" query pulling in the heavy-vaginal-
# bleeding-during-pregnancy article, purely because both mention "mild"
# and "gradually") — nonzero relevance, but far weaker than the top match,
# and confusing/alarming to show alongside it. This is a relative cutoff
# on top of retrieve()'s existing absolute one, not a replacement for it.
_RELEVANCE_RATIO = 0.5


def _filter_to_relevant(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    if not chunks or chunks[0].score <= 0:
        return chunks
    threshold = chunks[0].score * _RELEVANCE_RATIO
    return [c for c in chunks if c.score >= threshold]


class RagGroundedExplanation:
    def __init__(self, explanation: str, sources: list[str], generation_source: str):
        self.explanation = explanation
        self.sources = sources
        # "extractive" | "llm_grounded" | "llm_rejected_ungrounded" | "no_context"
        # — surfaced mainly for the audit trail / eval work, not (yet) the API response.
        self.generation_source = generation_source


def _build_query(symptom: SymptomInput) -> str:
    return " ".join(symptom.symptom_ids) + " " + symptom.free_text


async def generate_explanation(
    symptom: SymptomInput,
    escalation: EscalationResult,
    retriever: RetrieverProtocol | None = None,
    language: str = "en",
) -> RagGroundedExplanation:
    no_context_fallback = _NO_CONTEXT_FALLBACK.get(language, _NO_CONTEXT_FALLBACK["en"])
    retriever = retriever or get_default_retriever(language=language)
    query = _build_query(symptom)
    chunks = _filter_to_relevant(retriever.retrieve(query, k=3))

    if not chunks:
        return RagGroundedExplanation(
            explanation=escalation.guidance, sources=[], generation_source="no_context"
        )

    llm = get_llm_client()
    sources = sorted({c.chunk.title for c in chunks})

    if isinstance(llm, ExtractiveFallbackClient):
        explanation_text = llm.generate_from_chunks(chunks)
        if not explanation_text.strip():
            explanation_text = no_context_fallback
        return RagGroundedExplanation(
            explanation=explanation_text, sources=sources, generation_source="extractive"
        )

    if isinstance(llm, AnthropicLLMClient):
        prompt = build_grounded_prompt(
            symptom.symptom_ids, escalation.guidance, chunks, language=language
        )
        explanation_text = llm.generate(prompt)

        if explanation_text.strip() and is_grounded(explanation_text, chunks):
            return RagGroundedExplanation(
                explanation=explanation_text, sources=sources, generation_source="llm_grounded"
            )

        # Generated text was empty or failed the groundedness check — fall
        # back to the extractive client's verbatim-quote behavior rather
        # than showing the patient an ungrounded (or blank) explanation.
        fallback_text = ExtractiveFallbackClient().generate_from_chunks(chunks)
        return RagGroundedExplanation(
            explanation=fallback_text or no_context_fallback,
            sources=sources,
            generation_source="llm_rejected_ungrounded",
        )

    raise TypeError(f"Unhandled LLM client type: {type(llm)!r}")  # pragma: no cover - defensive
