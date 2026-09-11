"""LangChain adapter for the project's auditable knowledge service.

The SQLite knowledge catalogue remains authoritative.  This adapter only
translates retrieval results into LangChain ``Document`` objects, preserving
the task snapshot and stable evidence IDs used by report citations.
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from .runtime import initialize_session, service_for, settings


class FinancialKnowledgeRetriever(BaseRetriever):
    """Expose ``KnowledgeBaseService`` through LangChain's retriever protocol."""

    service: Any = Field(exclude=True)
    kb_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 8
    snapshot: list[dict[str, Any]] | None = Field(default=None, exclude=True)
    research_memory: Any = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def _search(self, query: str) -> list[Document]:
        response = await self.service.search(
            query=query,
            kb_ids=self.kb_ids,
            filters=self.filters,
            top_k=self.top_k,
            snapshot=self.snapshot,
        )
        documents = []
        for item in response["results"]:
            metadata = {
                **item.get("metadata", {}),
                "evidence_id": item["evidence_id"],
                "document_id": item["doc_id"],
                "knowledge_base_id": item["kb_id"],
                "title": item["title"],
                "locator": item["locator"],
                "page": item.get("page"),
                "kind": item.get("kind"),
                "version": item["version"],
                "retrieval_score": item["score"],
                "retrieval_mode": response["mode"],
            }
            documents.append(Document(page_content=item["text"], metadata=metadata))

        memory = self.research_memory
        if memory is not None and getattr(memory, "knowledge_state", None):
            state = memory.knowledge_state
            state.setdefault("queries", {})[query] = response
            evidence = state.setdefault("evidence", {})
            for item in response["results"]:
                evidence[item["evidence_id"]] = item
            memory.save()
        return documents

    async def _aget_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        return await self._search(query)

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._search(query))
        raise RuntimeError("Use 'await retriever.ainvoke(query)' inside an async application")

    async def evidence_pack(self, query: str) -> dict[str, Any]:
        """Return a serializable evidence pack for graph state and API clients."""
        documents = await self._search(query)
        return {
            "query": query,
            "evidence_ids": [doc.metadata["evidence_id"] for doc in documents],
            "documents": [
                {"text": doc.page_content, "metadata": dict(doc.metadata)}
                for doc in documents
            ],
        }


def retriever_for(memory: Any) -> FinancialKnowledgeRetriever | None:
    """Build a task-pinned retriever from the current Memory object."""
    opts = settings(memory.config)
    if not opts["enabled"]:
        return None
    if not getattr(memory, "knowledge_state", None):
        initialize_session(memory)
    filters = {**opts.get("filters", {}), "as_of": opts.get("as_of", "")}
    return FinancialKnowledgeRetriever(
        service=service_for(memory.config),
        kb_ids=list(opts["kb_ids"]),
        filters=filters,
        top_k=int(opts["top_k"]),
        snapshot=memory.knowledge_state["corpus"],
        research_memory=memory,
    )
