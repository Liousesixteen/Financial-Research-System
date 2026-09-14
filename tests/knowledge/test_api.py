from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.knowledge.api import create_router, KnowledgeSettings
from src.knowledge.service import KnowledgeBaseService
import pytest


@pytest.fixture
def client(tmp_path):
    app = FastAPI(); service = KnowledgeBaseService(tmp_path)
    app.include_router(create_router(lambda: service))
    with TestClient(app) as client:
        yield client


def test_upload_search_preview_reindex_delete(client):
    kb = client.post('/api/knowledge/libraries', json={'name': 'Test'}).json()['id']
    response = client.post(f'/api/knowledge/libraries/{kb}/documents', files={'file': ('report.txt', b'margin rose', 'text/plain')}, data={'metadata': '{"published_at":"2025-01-01"}'})
    assert response.status_code == 202
    doc = response.json()['doc_id']
    assert client.get('/api/knowledge/jobs/' + response.json()['job_id']).json()['status'] == 'ready'
    result = client.post('/api/knowledge/search', json={'kb_ids': [kb], 'query': 'margin'}).json()
    assert result['results'][0]['doc_id'] == doc
    preview = client.get('/api/knowledge/documents/' + doc).json()
    assert preview['chunks'][0]['text'] == 'margin rose'
    assert client.get(f'/api/knowledge/documents/{doc}/original').content == b'margin rose'
    assert client.post(f'/api/knowledge/documents/{doc}/reindex').status_code == 202
    assert client.delete('/api/knowledge/documents/' + doc).status_code == 200
    assert client.get(f'/api/knowledge/documents/{doc}/original').status_code == 404
    assert not client.post('/api/knowledge/search', json={'kb_ids': [kb], 'query': 'margin'}).json()['results']


def test_api_validation_and_library_rename(client):
    kb = client.post('/api/knowledge/libraries', json={'name': 'Test'}).json()['id']
    assert client.patch('/api/knowledge/libraries/' + kb, json={'name': 'Renamed'}).status_code == 200
    assert client.get('/api/knowledge/libraries').json()['libraries'][0]['name'] == 'Renamed'
    assert client.post('/api/knowledge/search', json={'kb_ids': [kb], 'query': 'x', 'top_k': 0}).status_code == 422
    assert client.post(f'/api/knowledge/libraries/{kb}/documents', files={'file': ('a.txt', b'content')}, data={'metadata': '[]'}).status_code == 422
    with pytest.raises(ValueError): KnowledgeSettings(enabled=True)
    with pytest.raises(ValueError): KnowledgeSettings(as_of='not-date')


def test_grounded_answer_requires_model_and_valid_evidence(tmp_path, client):
    assert client.get('/api/knowledge/capabilities').json() == {'answer': False}
    kb = client.post('/api/knowledge/libraries', json={'name': 'Sources'}).json()['id']
    assert client.post('/api/knowledge/answer', json={'kb_ids': [kb], 'query': 'margin'}).status_code == 503

    service = KnowledgeBaseService(tmp_path / 'answer-kb')
    library = service.create_library('Sources')['id']
    entry = service.enqueue(library, 'report.txt', b'margin increased from 10% to 12%')
    import asyncio
    asyncio.run(service.process(entry['job_id']))

    class Model:
        def __init__(self): self.invalid = False; self.calls = 0
        async def generate(self, messages):
            self.calls += 1
            import re
            evidence_id = re.search(r'\[KB:([a-f0-9]{32})\]', messages[1]['content']).group(1)
            if self.invalid:
                evidence_id = '0' * 32
            return f'Margin increased from 10% to 12% [KB:{evidence_id}]'

    model = Model()
    app = FastAPI()
    app.include_router(create_router(lambda: service, lambda: model))
    with TestClient(app) as answer_client:
        assert answer_client.get('/api/knowledge/capabilities').json() == {'answer': True}
        request = {'kb_ids': [library], 'query': 'margin'}
        assert answer_client.post('/api/knowledge/answer', json={**request, 'top_k': 9}).status_code == 422
        response = answer_client.post('/api/knowledge/answer', json=request)
        assert response.status_code == 200
        payload = response.json()
        assert len(payload['citations']) == 1
        assert payload['citations'][0]['evidence_id'] in payload['answer']
        model.invalid = True
        rejected = answer_client.post('/api/knowledge/answer', json=request).json()
        assert rejected['citations'] == [] and '未生成可核验' in rejected['answer']
        no_evidence = answer_client.post('/api/knowledge/answer', json={'kb_ids': ['missing'], 'query': 'margin'}).json()
        assert no_evidence['citations'] == [] and model.calls == 2
        async def unavailable(messages):
            raise ConnectionError('offline')
        model.generate = unavailable
        assert answer_client.post('/api/knowledge/answer', json=request).status_code == 503


def test_strict_semantic_error_is_visible_to_api(tmp_path):
    service = KnowledgeBaseService(tmp_path, require_semantic=True)
    kb = service.create_library('Sources')['id']
    entry = service.enqueue(kb, 'report.txt', b'margin increased')
    import asyncio
    asyncio.run(service.process(entry['job_id']))
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    with TestClient(app) as test_client:
        response = test_client.post('/api/knowledge/search', json={'kb_ids': [kb], 'query': 'margin'})
        assert response.status_code == 422
        assert 'embedding model' in response.json()['detail']
