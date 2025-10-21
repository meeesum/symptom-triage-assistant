"""Pluggable embedding client for dense retrieval.

Two implementations, same pattern as app/rag/llm_client.py:

  - FastEmbedClient: real embeddings via `fastembed` (BAAI/bge-small-en-v1.5,
    384-dim, ONNX runtime). Deliberately NOT sentence-transformers/torch —
    torch has no distribution for this project's Python version in this
    environment, and fastembed gives the same class of embedding model
    without that dependency. Downloads its model from the HF Hub on first
    use (~15s, one-time, network required) then runs fully locally.
  - DeterministicFakeEmbeddingClient: no model, no network, no torch/onnx —
    a stable hashed bag-of-words vector (word -> index via md5, L2
    normalized). It is NOT a semantic embedding (it can't tell "chest
    pain" and "cardiac discomfort" are related), but it preserves the one
    property the dense-retrieval tests actually need: texts sharing words
    score higher than texts that don't, deterministically, offline, in
    microseconds. This is what tests use by default — see EMBEDDING_FAKE
    in tests/conftest.py — for the same reason tests use fakeredis and the
    extractive LLM fallback: fast, offline, zero-setup.

get_embedding_client() defaults to the real FastEmbedClient; set
EMBEDDING_FAKE=1 to use the deterministic fake instead.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from functools import lru_cache

_FAKE_DIM = 1024
_WORD_RE = re.compile(r"[a-z0-9]+")


class EmbeddingClient(ABC):
    dimension: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedClient(EmbeddingClient):
    """Real embeddings via fastembed's ONNX-based BAAI/bge-small-en-v1.5."""

    dimension = 384

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding  # local import: only needed on this path

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]


class DeterministicFakeEmbeddingClient(EmbeddingClient):
    """Hashed bag-of-words vector — deterministic, offline, word-overlap-preserving."""

    dimension = _FAKE_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * _FAKE_DIM
        for word in _WORD_RE.findall(text.lower()):
            index = int(hashlib.md5(word.encode()).hexdigest(), 16) % _FAKE_DIM
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    if os.environ.get("EMBEDDING_FAKE") == "1":
        return DeterministicFakeEmbeddingClient()
    return FastEmbedClient()
