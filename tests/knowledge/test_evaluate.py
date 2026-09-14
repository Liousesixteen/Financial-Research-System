import pytest

from src.knowledge.evaluate import evaluate
from src.knowledge.service import KnowledgeBaseService


@pytest.mark.asyncio
async def test_retrieval_metrics_use_hand_labelled_evidence(tmp_path):
    service = KnowledgeBaseService(tmp_path)
    kb = service.create_library('A')['id']
    entry = service.enqueue(kb, 'report.txt', b'margin increased')
    await service.process(entry['job_id'])
    evidence_id = service.corpus([kb])[0]['id']
    result = await evaluate(service, [
        {'query': 'margin', 'relevant_ids': [evidence_id]},
        {'query': 'margin', 'relevant_ids': ['not-present']},
        {'query': 'margin', 'relevant_ids': [], 'kb_ids': ['missing-library']},
    ], [kb], top_k=1)
    assert result['hit_at_k'] == result['recall_at_k'] == result['mrr_at_k'] == 0.5
    assert result['no_answer_accuracy'] == 1.0
    assert result['details'][0]['retrieved_ids'] == [evidence_id]
    assert result['mean_latency_ms'] >= 0
