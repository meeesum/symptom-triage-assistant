"""TF-IDF retrieval index over the knowledge base — the default retriever.

TF-IDF + cosine similarity was the original bootstrap choice (zero external
dependencies at query time, fully testable offline) and stays the default
today: it works reasonably well because medical terminology is fairly
literal (symptom names/synonyms overlap with query terms), but it does NOT
generalize to paraphrased or colloquial patient language ("my chest feels
tight" vs "chest_pain"). app.rag.dense_retriever.DenseRetriever closes that
gap with fastembed + Qdrant embeddings and implements the exact same
`retrieve(query, k) -> list[ScoredChunk]` interface, so callers never touch
which one they got — see get_default_retriever() below and
docs/phase6a-dense-retrieval.md for why TF-IDF is still the default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import Protocol

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.rag.knowledge_base import Chunk, load_chunks

# scikit-learn's TfidfVectorizer only ships a built-in stopword list for
# "english" — passing stop_words="english" against Spanish text does
# nothing, so short high-frequency Spanish function words (de, la, el,
# en, que...) inflate the score of any article that happens to repeat
# them, degrading ranking quality. A short hand-rolled list closes most
# of that gap; it is not a linguistically complete stopword list (see
# docs/phase9b-internationalization.md).
_SPANISH_STOP_WORDS_TEXT = """
    de la que el en y a los del se las por un para con no una su al lo como
    más pero sus le ya o este sí porque esta entre cuando muy sin sobre
    también me hasta hay donde quien desde todo nos durante todos uno les
    ni contra otros ese eso ante ellos e esto mí antes algunos qué unos yo
    otro otras otra él tanto esa estos mucho quienes nada muchos cual poco
    ella estar estas algunas algo nosotros mi mis tú te ti tu tus ellas
    nosotras vosotros vosotras os mío mía míos mías tuyo tuya tuyos tuyas
    suyo suya suyos suyas nuestro nuestra nuestros nuestras vuestro vuestra
    vuestros vuestras esos esas
"""
_SPANISH_STOP_WORDS = frozenset(_SPANISH_STOP_WORDS_TEXT.split())


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class RetrieverProtocol(Protocol):
    def retrieve(self, query: str, k: int = 3, min_score: float = 0.05) -> list[ScoredChunk]: ...


class Retriever:
    def __init__(self, chunks: list[Chunk], language: str = "en"):
        if not chunks:
            raise ValueError("Retriever requires at least one chunk")
        self._chunks = chunks
        stop_words = "english" if language != "es" else list(_SPANISH_STOP_WORDS)
        self._vectorizer = TfidfVectorizer(stop_words=stop_words)
        self._matrix = self._vectorizer.fit_transform([c.text for c in chunks])

    def retrieve(self, query: str, k: int = 3, min_score: float = 0.05) -> list[ScoredChunk]:
        if not query.strip():
            return []
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix)[0]

        ranked = sorted(
            zip(self._chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True
        )
        return [
            ScoredChunk(chunk=chunk, score=float(score))
            for chunk, score in ranked[:k]
            if score >= min_score
        ]


@cache
def get_default_retriever(language: str = "en") -> RetrieverProtocol:
    """Process-wide singleton per language so each index is built once, not
    per-request. `lru_cache` keys on `language` automatically, so this
    stays a plain singleton for the (overwhelmingly common) single-language
    case while still giving each requested language its own cached index.

    RETRIEVAL_BACKEND=dense switches to app.rag.dense_retriever.DenseRetriever
    (fastembed + Qdrant — see that module's docstring). Default stays TF-IDF:
    dense retrieval is opt-in until it's had real pilot validation, per
    docs/phase6a-dense-retrieval.md.
    """
    chunks = load_chunks(language=language)
    if os.environ.get("RETRIEVAL_BACKEND") == "dense":
        from app.rag.dense_retriever import DenseRetriever  # local: keeps qdrant/fastembed off

        return DenseRetriever(chunks)
    return Retriever(chunks, language=language)
