"""Knowledge routes usable with the full app or a standalone local library UI."""
import asyncio
import json
from datetime import date
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator


class KnowledgeSettings(BaseModel):
    enabled: bool = False
    kb_ids: list[str] = Field(default_factory=list)
    mode: Literal['hybrid', 'knowledge_only'] = 'hybrid'
    as_of: str = ''
    top_k: int = Field(default=8, ge=1, le=30)
    vector_backend: Literal['local', 'qdrant'] = 'local'
    qdrant_url: str = 'http://localhost:6333'
    embedding_model: str = ''
    embedding_version: str = '1'
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator('as_of')
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value

    @model_validator(mode='after')
    def selected_library(self):
        if self.enabled and not self.kb_ids:
            raise ValueError('Select at least one knowledge base')
        return self


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    kb_ids: list[str] = Field(min_length=1, max_length=100)
    filters: dict = Field(default_factory=dict)
    top_k: int = Field(default=8, ge=1, le=30)


def create_router(get_service):
    router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])

    def safely(fn, *args):
        try:
            return fn(*args)
        except KeyError:
            raise HTTPException(404, 'Knowledge base or document not found')
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.get('/libraries')
    def libraries():
        return {'libraries': get_service().libraries()}

    @router.post('/libraries', status_code=201)
    def create(request: NameRequest):
        return safely(get_service().create_library, request.name)

    @router.patch('/libraries/{kb_id}')
    def rename(kb_id: str, request: NameRequest):
        safely(get_service().rename_library, kb_id, request.name)
        return {'status': 'success'}

    @router.get('/libraries/{kb_id}/documents')
    def documents(kb_id: str):
        return {'documents': get_service().documents(kb_id)}

    @router.post('/libraries/{kb_id}/documents', status_code=202)
    async def upload(kb_id: str, background_tasks: BackgroundTasks,
                     file: UploadFile = File(...), metadata: str = Form('{}')):
        try:
            meta = json.loads(metadata)
            if not isinstance(meta, dict):
                raise ValueError('Metadata must be an object')
        except (ValueError, TypeError):
            raise HTTPException(422, 'Invalid metadata JSON')
        try:
            content = await file.read(50 * 1024 * 1024 + 1)
        finally:
            await file.close()
        service = get_service()
        result = safely(service.enqueue, kb_id, file.filename or '', content, meta)
        if result['job_id']:
            background_tasks.add_task(service.process, result['job_id'])
        return result

    @router.get('/documents/{doc_id}')
    def document(doc_id: str):
        service = get_service()
        doc = safely(service.document, doc_id)
        with service.db() as db:
            chunks = [dict(r) for r in db.execute('SELECT * FROM chunks WHERE doc_id=? ORDER BY rowid', (doc_id,))]
        return {'document': doc, 'chunks': chunks}

    @router.get('/documents/{doc_id}/original')
    def original(doc_id: str):
        service = get_service()
        doc = safely(service.document, doc_id)
        path = safely(service.original_path, doc_id)
        mime = 'application/pdf' if path.suffix == '.pdf' else 'application/octet-stream'
        return FileResponse(path, filename=doc['filename'], media_type=mime,
                            content_disposition_type='inline' if path.suffix == '.pdf' else 'attachment',
                            headers={'X-Content-Type-Options': 'nosniff'})

    @router.delete('/documents/{doc_id}')
    def delete(doc_id: str):
        safely(get_service().delete_document, doc_id)
        return {'status': 'deleted'}

    @router.post('/documents/{doc_id}/reindex', status_code=202)
    def reindex(doc_id: str, background_tasks: BackgroundTasks):
        service = get_service()
        job_id = safely(service.retry, doc_id)
        background_tasks.add_task(service.process, job_id)
        return {'job_id': job_id}

    @router.get('/jobs/{job_id}')
    def job(job_id: str):
        return safely(get_service().job, job_id)

    @router.post('/search')
    async def search(request: SearchRequest):
        try:
            return await get_service().search(request.query, request.kb_ids, request.filters, request.top_k)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    return router
