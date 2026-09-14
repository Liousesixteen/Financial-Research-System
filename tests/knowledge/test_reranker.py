import pytest

from src.knowledge import reranker as reranker_module


@pytest.mark.asyncio
async def test_cross_encoder_adapter_scores_query_document_pairs(monkeypatch):
    class Model:
        def predict(self, pairs, batch_size):
            assert pairs == [('margin?', 'margin rose'), ('margin?', 'revenue fell')]
            assert batch_size == 2
            return [2.0, -1.0]
    monkeypatch.setattr(reranker_module, '_load_model', lambda name: Model())
    reranker = reranker_module.CrossEncoderReranker('test-model', batch_size=2)
    assert await reranker.score('margin?', ['margin rose', 'revenue fell']) == [2.0, -1.0]
