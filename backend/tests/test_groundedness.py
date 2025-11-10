from app.rag.groundedness import groundedness_score, is_grounded
from app.rag.knowledge_base import Chunk
from app.rag.retriever import ScoredChunk


def _scored(text: str) -> ScoredChunk:
    chunk = Chunk(text=text, article_id="test", title="Test Article", source_note="", tags=())
    return ScoredChunk(chunk=chunk, score=1.0)


class TestGroundednessScore:
    def test_explanation_reusing_context_vocabulary_scores_high(self):
        chunks = [_scored("Chest pain combined with sweating can indicate a heart attack.")]
        explanation = "This combination of chest pain and sweating can indicate a heart attack."
        assert groundedness_score(explanation, chunks) >= 0.7

    def test_explanation_with_unrelated_vocabulary_scores_low(self):
        chunks = [_scored("Chest pain combined with sweating can indicate a heart attack.")]
        explanation = "Quantum computing relies on superposition and entanglement principles."
        assert groundedness_score(explanation, chunks) < 0.2

    def test_empty_explanation_scores_zero(self):
        chunks = [_scored("Some context text here.")]
        assert groundedness_score("", chunks) == 0.0

    def test_no_chunks_scores_zero(self):
        assert groundedness_score("Some explanation text.", []) == 0.0

    def test_short_words_are_ignored_so_they_cant_inflate_the_score(self):
        # "is", "a", "to" etc are common across any two unrelated texts —
        # if they counted, almost anything would look "grounded".
        chunks = [_scored("Symptoms of a severe allergic reaction include swelling.")]
        explanation = "It is to be or not to be, a question for the ages."
        assert groundedness_score(explanation, chunks) < 0.3


class TestIsGrounded:
    def test_default_threshold_accepts_high_overlap(self):
        chunks = [_scored("Severe abdominal pain during pregnancy needs urgent evaluation.")]
        explanation = "Severe abdominal pain during pregnancy needs urgent medical evaluation right away."
        assert is_grounded(explanation, chunks) is True

    def test_default_threshold_rejects_low_overlap(self):
        chunks = [_scored("Severe abdominal pain during pregnancy needs urgent evaluation.")]
        explanation = "Drink plenty of fluids and get adequate rest during your recovery period."
        assert is_grounded(explanation, chunks) is False
