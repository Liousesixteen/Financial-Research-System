"""Optional cross-encoder reranking for the knowledge retrieval pipeline."""

import asyncio
import math
from functools import lru_cache


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model_name)


class CrossEncoderReranker:
    def __init__(self, model_name: str, batch_size: int = 16):
        if not model_name.strip():
            raise ValueError('Reranker model name is required')
        self.model_name = model_name
        self.batch_size = batch_size

    def _predict(self, query: str, texts: list[str]) -> list[float]:
        model = _load_model(self.model_name)
        scores = model.predict([(query, text) for text in texts], batch_size=self.batch_size)
        result = [float(score) for score in scores]
        if len(result) != len(texts) or not all(math.isfinite(score) for score in result):
            raise ValueError('Reranker returned invalid scores')
        return result

    async def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        return await asyncio.to_thread(self._predict, query, texts)
