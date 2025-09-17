"""Groundedness check for LLM-generated explanations.

Only matters for the real Anthropic path — the extractive fallback client
(app/rag/llm_client.py) quotes retrieved chunks verbatim and is grounded
by construction, so it's never run through this check.

Two implementations, same pluggable pattern as app.rag.llm_client's
LLMClient and app.rag.embeddings' EmbeddingClient:

  - LexicalOverlapChecker (default): measures what fraction of the
    *distinct content words* in the generated explanation also appear
    somewhere in the retrieved context. Zero-setup, offline, deterministic
    — but NOT a semantic entailment check: it will not catch a subtly
    wrong paraphrase or a flipped claim that happens to reuse the right
    vocabulary ("chest pain resolves on its own" vs "chest pain requires
    emergency care" could both score high, since both sentences share
    most of their words). It catches the cheaper, more common failure
    mode instead: the model drifting away from the context entirely and
    generating from general knowledge, which shows up as low vocabulary
    overlap.
  - LLMEntailmentChecker: a genuine semantic check — a second Anthropic
    call asking "does this explanation actually follow from this
    context?" This is the real entailment check the module's own
    docstring used to name as the "intended production upgrade," now
    built. Deliberately NOT an embedding-cosine-similarity check: generic
    sentence embeddings (the kind app/rag/embeddings.py's FastEmbedClient
    produces) are good at topic similarity but not reliable at telling a
    supported claim from a topically-similar contradiction of it — the
    exact "chest pain resolves on its own" failure mode above would
    likely still score high on embedding similarity, since both sentences
    are about the same topic in similar words. An LLM judgment call is a
    materially different (and stronger) check, not just a reimplementation
    of the same idea with a fancier similarity metric. A real NLI
    cross-encoder model would be a further upgrade, but those need
    `torch`, which has no distribution for this project's Python version
    in this environment (see docs/phase6a-dense-retrieval.md for the same
    constraint hit there).

GROUNDEDNESS_METHOD=llm opts into the real check (requires
ANTHROPIC_API_KEY, since it's an Anthropic call). Default stays lexical:
free, offline, and — critically — this check runs on every real-LLM-path
response, so a "safety check" that itself makes an extra paid network
call on every request is a real cost/latency tradeoff a deployment should
opt into deliberately, not get by default. See
docs/phase6d-semantic-groundedness.md.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod

from app.rag.retriever import ScoredChunk

_WORD_RE = re.compile(r"[a-z]+")
_MIN_WORD_LEN = 4  # filters out short, low-information words without a stopword list

DEFAULT_MIN_OVERLAP = 0.4

ENTAILMENT_PROMPT_TEMPLATE = """You are checking whether a claim is actually supported by a \
piece of source context — not just related to the same topic, but genuinely following from \
what the context says, with no contradiction and no unsupported addition.

Context:
{context}

Claim:
{explanation}

Does the claim follow from the context? Answer with exactly one word: "yes" or "no".
"""


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= _MIN_WORD_LEN}


def groundedness_score(explanation: str, chunks: list[ScoredChunk]) -> float:
    """Fraction of the explanation's distinct content words that also
    appear in the retrieved context. Returns 0.0 for an empty explanation
    or when there's no context to check against. Lexical, not semantic —
    see this module's docstring."""
    explanation_words = _content_words(explanation)
    if not explanation_words:
        return 0.0

    context_text = " ".join(c.chunk.text for c in chunks)
    context_words = _content_words(context_text)
    if not context_words:
        return 0.0

    overlap = explanation_words & context_words
    return len(overlap) / len(explanation_words)


class EntailmentChecker(ABC):
    @abstractmethod
    def check(self, explanation: str, chunks: list[ScoredChunk]) -> bool: ...


class LexicalOverlapChecker(EntailmentChecker):
    def __init__(self, min_overlap: float = DEFAULT_MIN_OVERLAP):
        self._min_overlap = min_overlap

    def check(self, explanation: str, chunks: list[ScoredChunk]) -> bool:
        return groundedness_score(explanation, chunks) >= self._min_overlap


class LLMEntailmentChecker(EntailmentChecker):
    def __init__(self, model: str | None = None):
        import anthropic  # local import: only required when this path is used

        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    def check(self, explanation: str, chunks: list[ScoredChunk]) -> bool:
        if not explanation.strip() or not chunks:
            return False

        context = "\n\n".join(c.chunk.text for c in chunks)
        prompt = ENTAILMENT_PROMPT_TEMPLATE.format(context=context, explanation=explanation)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().lower()
        return answer.startswith("yes")


def get_entailment_checker() -> EntailmentChecker:
    if os.environ.get("GROUNDEDNESS_METHOD") == "llm":
        return LLMEntailmentChecker()
    return LexicalOverlapChecker()


def is_grounded(
    explanation: str,
    chunks: list[ScoredChunk],
    min_overlap: float = DEFAULT_MIN_OVERLAP,
    checker: EntailmentChecker | None = None,
) -> bool:
    """checker defaults to get_entailment_checker() (lexical unless
    GROUNDEDNESS_METHOD=llm). min_overlap is only used when the resolved
    checker is a LexicalOverlapChecker constructed here (i.e. neither an
    explicit checker nor GROUNDEDNESS_METHOD=llm was given) — kept for
    backward compatibility with callers that only want to adjust the
    lexical threshold without touching the pluggable-checker machinery.
    """
    if checker is None and os.environ.get("GROUNDEDNESS_METHOD") != "llm":
        checker = LexicalOverlapChecker(min_overlap=min_overlap)
    checker = checker or get_entailment_checker()
    return checker.check(explanation, chunks)
