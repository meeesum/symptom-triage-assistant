"""Dense-embedding retrieval over the knowledge base, via Qdrant.

Same interface as app.rag.retriever.Retriever (retrieve(query, k,
min_score) -> list[ScoredChunk]) so app/rag/pipeline.py doesn't care which
one it got — this is the swap the TF-IDF retriever's own docstring already
called out as the intended production replacement.

Backing store: qdrant-client in local mode (`location=":memory:"`) by
default — this is a real Qdrant engine running in-process, not a mock,
just like fakeredis is a real Redis reimplementation rather than a stub.
Set QDRANT_URL to point at a real Qdrant server instead (same
zero-setup-default / real-service-optional pattern as Postgres and Redis).

TF-IDF is kept as the default retriever (see get_default_retriever() in
retriever.py) rather than deleted — dense retrieval is opt-in via
RETRIEVAL_BACKEND=dense until it's had real pilot usage to validate
against, per docs/phase6a-dense-retrieval.md.
"""

from __future__ import annotations

import os

from app.rag.embeddings import EmbeddingClient, get_embedding_client
from app.rag.knowledge_base import Chunk
from app.rag.retriever import ScoredChunk

_COLLECTION = "knowledge_base"


class DenseRetriever:
    def __init__(self, chunks: list[Chunk], embedding_client: EmbeddingClient | None = None):
        if not chunks:
            raise ValueError("DenseRetriever requires at least one chunk")

        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        self._chunks = chunks
        self._embedder = embedding_client or get_embedding_client()

        qdrant_url = os.environ.get("QDRANT_URL")
        self._client = QdrantClient(url=qdrant_url) if qdrant_url else QdrantClient(
            location=":memory:"
        )
        if self._client.collection_exists(_COLLECTION):
            self._client.delete_collection(_COLLECTION)
        self._client.create_collection(
            _COLLECTION,
            vectors_config=VectorParams(size=self._embedder.dimension, distance=Distance.COSINE),
        )

        vectors = self._embedder.embed([c.text for c in chunks])
        self._client.upsert(
            _COLLECTION,
            points=[
                PointStruct(id=i, vector=vector, payload={"chunk_index": i})
                for i, vector in enumerate(vectors)
            ],
        )

    def retrieve(self, query: str, k: int = 3, min_score: float = 0.05) -> list[ScoredChunk]:
        if not query.strip():
            return []

        query_vector = self._embedder.embed([query])[0]
        results = self._client.query_points(_COLLECTION, query=query_vector, limit=k).points

        return [
            ScoredChunk(
                chunk=self._chunks[point.payload["chunk_index"]], score=float(point.score)
            )
            for point in results
            if point.score >= min_score
        ]
