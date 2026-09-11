from types import SimpleNamespace

import pytest

from src.knowledge.langchain_retriever import retriever_for
from src.knowledge.runtime import initialize_session
from src.knowledge.service import KnowledgeBaseService


@pytest.mark.asyncio
async def test_langchain_retriever_preserves_snapshot_and_evidence_metadata(tmp_path):
    service = KnowledgeBaseService(tmp_path / "kb")
    library = service.create_library("annual reports")["id"]
    upload = service.enqueue(
        library,
        "annual-report.txt",
        b"Operating margin increased from 10 percent to 12 percent.",
        {"ticker": "TEST", "published_at": "2025-03-01", "source_type": "annual_report"},
    )
    await service.process(upload["job_id"])

    config = SimpleNamespace(
        config={
            "knowledge_base": {
                "enabled": True,
                "kb_ids": [library],
                "mode": "hybrid",
                "storage_dir": str(tmp_path / "kb"),
                "filters": {"ticker": "TEST"},
            }
        },
        llm_dict={},
    )
    memory = SimpleNamespace(config=config, knowledge_state={}, save=lambda: None)
    initialize_session(memory)
    retriever = retriever_for(memory)
    documents = await retriever.ainvoke("operating margin")

    assert len(documents) == 1
    document = documents[0]
    assert document.metadata["evidence_id"]
    assert document.metadata["ticker"] == "TEST"
    assert document.metadata["locator"] == "paragraph 1"
    assert document.metadata["retrieval_mode"] == "keyword"
    assert document.metadata["evidence_id"] in memory.knowledge_state["evidence"]
    assert "snapshot" not in retriever.model_dump()
    assert "research_memory" not in retriever.model_dump()


def test_langchain_retriever_is_disabled_with_knowledge_base(tmp_path):
    config = SimpleNamespace(config={"knowledge_base": {"enabled": False}}, llm_dict={})
    memory = SimpleNamespace(config=config, knowledge_state={}, save=lambda: None)
    assert retriever_for(memory) is None
