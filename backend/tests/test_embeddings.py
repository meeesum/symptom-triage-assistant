from app.rag.embeddings import DeterministicFakeEmbeddingClient, get_embedding_client


def test_fake_embedder_is_deterministic():
    client = DeterministicFakeEmbeddingClient()
    a = client.embed(["chest pain and shortness of breath"])[0]
    b = client.embed(["chest pain and shortness of breath"])[0]
    assert a == b


def test_fake_embedder_produces_correct_dimension():
    client = DeterministicFakeEmbeddingClient()
    vec = client.embed(["fever"])[0]
    assert len(vec) == client.dimension


def test_fake_embedder_overlapping_words_score_higher_than_unrelated():
    client = DeterministicFakeEmbeddingClient()
    query, related, unrelated = client.embed(
        [
            "chest pain shortness of breath",
            "chest pain and breathing difficulty",
            "xylophone quantum blockchain",
        ]
    )

    def cosine(u, v):
        return sum(x * y for x, y in zip(u, v, strict=True))

    assert cosine(query, related) > cosine(query, unrelated)


def test_fake_embedder_handles_empty_text():
    client = DeterministicFakeEmbeddingClient()
    vec = client.embed([""])[0]
    assert vec == [0.0] * client.dimension


def test_get_embedding_client_returns_fake_when_env_set(monkeypatch):
    monkeypatch.setenv("EMBEDDING_FAKE", "1")
    get_embedding_client.cache_clear()
    try:
        assert isinstance(get_embedding_client(), DeterministicFakeEmbeddingClient)
    finally:
        get_embedding_client.cache_clear()
