"""Pluggable LLM client for grounded explanation generation.

Two implementations:

  - AnthropicLLMClient: real API call, used when ANTHROPIC_API_KEY is set.
  - ExtractiveFallbackClient: no network call at all — deterministically
    composes an explanation from the retrieved chunks. Used whenever no API
    key is configured (e.g. this dev environment right now).

The fallback is not a toy: it's what keeps the RAG pipeline runnable and
testable end-to-end (CI, local dev, offline demos) without requiring
secrets, and it's a legitimate degraded-mode behavior for production too —
if the LLM provider is down, falling back to "here's the most relevant
verified passage verbatim" is safer than returning an error to a patient
mid-triage.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from app.rag.retriever import ScoredChunk


class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str: ...


class ExtractiveFallbackClient(LLMClient):
    """Deterministic, no-network client: stitches together the top retrieved
    chunks instead of generating new text. Never hallucinates because it
    never generates — it only quotes the knowledge base directly."""

    def generate(self, prompt: str) -> str:
        # The pipeline passes chunk text pre-formatted into the prompt; for
        # the fallback we don't actually need the LLM-style prompt at all,
        # so this client is invoked differently — see generate_from_chunks.
        raise NotImplementedError(
            "ExtractiveFallbackClient does not support free-text prompts; "
            "use generate_from_chunks()."
        )

    def generate_from_chunks(self, chunks: list[ScoredChunk]) -> str:
        if not chunks:
            return ""
        parts = [c.chunk.text for c in chunks[:2]]
        return " ".join(parts)


class AnthropicLLMClient(LLMClient):
    def __init__(self, model: str | None = None):
        import anthropic  # local import: only required when this path is used

        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


def get_llm_client() -> LLMClient:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLMClient()
    return ExtractiveFallbackClient()


GROUNDED_PROMPT_TEMPLATE = """You are a symptom-information assistant. You must ONLY use the \
context passages below to answer — do not add medical claims that are not \
supported by them. If the context is insufficient, say so plainly rather \
than guessing.

Patient-reported symptoms: {symptom_ids}
Deterministic safety-tier guidance (must not be contradicted): {tier_guidance}

Context passages:
{context}

Write a short (3-5 sentence), plain-language explanation for the patient \
that is consistent with the safety-tier guidance above and cites which \
passage(s) support each claim by title.{language_instruction}
"""

# Only exercised when ANTHROPIC_API_KEY is actually set — unverified in
# this sandbox, same caveat as every other real-LLM-call path in this
# project (see docs/phase9b-internationalization.md).
_LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}


def build_grounded_prompt(
    symptom_ids: list[str], tier_guidance: str, chunks: list[ScoredChunk], language: str = "en"
) -> str:
    context = "\n\n".join(
        f"[{c.chunk.title}]: {c.chunk.text}" for c in chunks
    )
    language_name = _LANGUAGE_NAMES.get(language, "English")
    language_instruction = (
        f" Write your entire response in {language_name}." if language != "en" else ""
    )
    return GROUNDED_PROMPT_TEMPLATE.format(
        symptom_ids=", ".join(symptom_ids) or "(none listed)",
        tier_guidance=tier_guidance,
        context=context or "(no relevant passages found)",
        language_instruction=language_instruction,
    )
