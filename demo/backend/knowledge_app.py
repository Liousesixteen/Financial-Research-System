"""Standalone library server; no LLM credentials required for keyword retrieval.
Run: python -m uvicorn demo.backend.knowledge_app:app --host 127.0.0.1 --port 8000
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.knowledge.api import create_router
from src.knowledge.service import KnowledgeBaseService


def get_service():
    return KnowledgeBaseService(os.getenv('FRS_KB_DIR', str(Path(__file__).resolve().parents[2] / 'data/knowledge')))


@asynccontextmanager
async def lifespan(app):
    service = get_service()
    for job_id in service.recover_jobs():
        await service.process(job_id)
    yield


app = FastAPI(title='Financial Research System Knowledge Library', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://localhost:5173', 'http://127.0.0.1:3000'],
                   allow_methods=['*'], allow_headers=['*'])
app.include_router(create_router(get_service))
