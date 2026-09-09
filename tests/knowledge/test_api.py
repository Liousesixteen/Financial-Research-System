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
