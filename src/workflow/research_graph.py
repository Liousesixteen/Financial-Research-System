"""Durable LangGraph workflow for the financial research pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from src.agents import DataAnalyzer, DataCollector, ReportGenerator
from src.knowledge.langchain_retriever import retriever_for
from src.knowledge.runtime import initialize_session, settings as knowledge_settings
from src.memory import Memory
from src.utils import get_logger


class ResearchState(TypedDict, total=False):
    """Serializable graph state. Large datasets remain in Memory/artifact files."""

    task_id: str
    research_query: str
    target_name: str
    stock_code: str
    target_type: str
    resume: bool
    phase: str
    status: Literal["pending", "running", "completed", "completed_with_warnings", "failed"]
    collect_tasks: list[str]
    analysis_tasks: list[str]
    collector_agent_ids: list[str]
    analyzer_agent_ids: list[str]
    report_agent_id: str
    evidence_ids: list[str]
    retrieval_queries: list[str]
    retrieval_rounds: int
    artifact_paths: list[str]
    errors: list[dict[str, str]]
    warnings: list[str]
    metrics: dict[str, int]
    started_at: str
    completed_at: str


StatusCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchGraphRunner:
    """Bind serializable LangGraph state to the existing Config and Memory runtime."""

    def __init__(
        self,
        config: Any,
        *,
        resume: bool = True,
        max_concurrent: int | None = None,
        status_callback: StatusCallback | None = None,
    ):
        self.config = config
        self.resume = resume
        self.max_concurrent = max_concurrent
        self.status_callback = status_callback
        self.memory = Memory(config=config)
        self.logger = get_logger()
        workflow = config.config.get("workflow", {})
        self.max_iterations = int(workflow.get("max_iterations", 20))
        self.max_generated_tasks = int(workflow.get("max_generated_tasks", 5))
        self.min_initial_evidence = int(workflow.get("min_initial_evidence", 3))
        self.max_retrieval_queries = int(workflow.get("max_retrieval_queries", 4))
        self.max_retrieval_rounds = int(workflow.get("max_retrieval_rounds", 1))
        self.fail_fast = bool(workflow.get("fail_fast", False))

    async def _emit(self, event: str, **payload: Any) -> None:
        if self.status_callback is None:
            return
        result = self.status_callback({"event": event, "timestamp": _utc_now(), **payload})
        if inspect.isawaitable(result):
            await result

    async def initialize(self, state: ResearchState) -> dict[str, Any]:
        if self.resume:
            loaded = self.memory.load()
            self.logger.info(f"LangGraph initialization: memory loaded={loaded}")
        if not self.memory.knowledge_state:
            initialize_session(self.memory)
        await self._emit("phase_start", phase="initialize")
        return {
            "phase": "initialize",
            "status": "running",
            "started_at": state.get("started_at") or _utc_now(),
            "errors": list(state.get("errors", [])),
            "warnings": list(state.get("warnings", [])),
        }

    async def plan(self, state: ResearchState) -> dict[str, Any]:
        await self._emit("phase_start", phase="plan")
        custom_collect = list(self.config.config.get("custom_collect_tasks", []))
        custom_analysis = list(self.config.config.get("custom_analysis_tasks", []))
        llm_name = os.getenv("DS_MODEL_NAME") or self._first_model_name()
        generate_tasks = bool(self.config.config.get("workflow", {}).get("generate_tasks", True))

        generated_collect: list[str] = []
        generated_analysis: list[str] = []
        if generate_tasks:
            if self.memory.generated_collect_tasks:
                generated_collect = self.memory.generated_collect_tasks
            else:
                generated_collect = await self.memory.generate_collect_tasks(
                    query=state["research_query"],
                    use_llm_name=llm_name,
                    max_num=self.max_generated_tasks,
                    existing_tasks=custom_collect,
                )
            if self.memory.generated_analysis_tasks:
                generated_analysis = self.memory.generated_analysis_tasks
            else:
                generated_analysis = await self.memory.generate_analyze_tasks(
                    query=state["research_query"],
                    use_llm_name=llm_name,
                    max_num=self.max_generated_tasks,
                    existing_tasks=custom_analysis,
                )

        collect_tasks = custom_collect + [task for task in generated_collect if task not in custom_collect]
        analysis_tasks = custom_analysis + [task for task in generated_analysis if task not in custom_analysis]
        self.memory.save()
        await self._emit(
            "phase_complete",
            phase="plan",
            collect_task_count=len(collect_tasks),
            analysis_task_count=len(analysis_tasks),
        )
        return {"phase": "plan", "collect_tasks": collect_tasks, "analysis_tasks": analysis_tasks}

    async def retrieve_initial_evidence(self, state: ResearchState) -> dict[str, Any]:
        """Prime the snapshot with broad evidence; agents can issue focused follow-up searches."""
        await self._emit("phase_start", phase="retrieve")
        retriever = retriever_for(self.memory)
        if retriever is None:
            await self._emit("phase_complete", phase="retrieve", evidence_count=0)
            return {"phase": "retrieve", "evidence_ids": [], "retrieval_queries": [], "retrieval_rounds": 0}
        documents = await retriever.ainvoke(state["research_query"])
        evidence_ids = [doc.metadata["evidence_id"] for doc in documents]
        await self._emit("phase_complete", phase="retrieve", evidence_count=len(evidence_ids))
        return {
            "phase": "retrieve",
            "evidence_ids": evidence_ids,
            "retrieval_queries": [state["research_query"]],
            "retrieval_rounds": 0,
        }

    async def assess_evidence(self, state: ResearchState) -> dict[str, Any]:
        """Expose the evidence gate as a checkpointed, observable graph phase."""
        await self._emit("phase_start", phase="assess_evidence")
        evidence_count = len(state.get("evidence_ids", []))
        await self._emit("phase_complete", phase="assess_evidence", evidence_count=evidence_count)
        warnings = list(state.get("warnings", []))
        opts = knowledge_settings(self.config)
        exhausted = state.get("retrieval_rounds", 0) >= self.max_retrieval_rounds
        if opts["enabled"] and evidence_count < self.min_initial_evidence and exhausted:
            warning = (
                f"Knowledge retrieval found {evidence_count} unique evidence item(s), "
                f"below the configured minimum of {self.min_initial_evidence}."
            )
            if warning not in warnings:
                warnings.append(warning)
        return {"phase": "assess_evidence", "warnings": warnings}

    def route_after_evidence(self, state: ResearchState) -> Literal["expand", "continue"]:
        opts = knowledge_settings(self.config)
        if not opts["enabled"]:
            return "continue"
        if len(state.get("evidence_ids", [])) >= self.min_initial_evidence:
            return "continue"
        if state.get("retrieval_rounds", 0) >= self.max_retrieval_rounds:
            return "continue"
        return "expand"

    async def expand_retrieval(self, state: ResearchState) -> dict[str, Any]:
        """Use planned research tasks as focused follow-up queries when evidence is sparse."""
        await self._emit("phase_start", phase="expand_retrieval")
        retriever = retriever_for(self.memory)
        if retriever is None:
            await self._emit("phase_complete", phase="expand_retrieval", query_count=0, evidence_count=0)
            return {"phase": "expand_retrieval", "retrieval_rounds": state.get("retrieval_rounds", 0) + 1}

        candidates = [
            f"{state['target_name']} {task}"
            for task in state.get("collect_tasks", []) + state.get("analysis_tasks", [])
        ]
        seen = set(state.get("retrieval_queries", []))
        queries = []
        for query in candidates:
            if query not in seen:
                queries.append(query)
                seen.add(query)
            if len(queries) >= self.max_retrieval_queries:
                break

        evidence_ids = list(state.get("evidence_ids", []))
        for query in queries:
            documents = await retriever.ainvoke(query)
            for document in documents:
                evidence_id = document.metadata["evidence_id"]
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        rounds = state.get("retrieval_rounds", 0) + 1
        await self._emit(
            "phase_complete",
            phase="expand_retrieval",
            query_count=len(queries),
            evidence_count=len(evidence_ids),
            retrieval_round=rounds,
        )
        return {
            "phase": "expand_retrieval",
            "evidence_ids": evidence_ids,
            "retrieval_queries": list(state.get("retrieval_queries", [])) + queries,
            "retrieval_rounds": rounds,
        }

    async def collect(self, state: ResearchState) -> dict[str, Any]:
        await self._emit("phase_start", phase="collect")
        target = self._research_target()
        specs = [
            {
                "agent_class": DataCollector,
                "task_input": {
                    "input_data": {"task": f"{target}, task: {task}"},
                    "echo": True,
                    "max_iterations": self.max_iterations,
                    "resume": self.resume,
                },
                "agent_kwargs": {"use_llm_name": os.getenv("DS_MODEL_NAME") or self._first_model_name()},
                "priority": 1,
                "task": task,
            }
            for task in state.get("collect_tasks", [])
        ]
        ids, errors = await self._run_agent_specs(specs, "collect")
        return self._phase_result(state, "collect", ids, errors, "collector_agent_ids")

    async def analyze(self, state: ResearchState) -> dict[str, Any]:
        await self._emit("phase_start", phase="analyze")
        target = self._research_target()
        specs = [
            {
                "agent_class": DataAnalyzer,
                "task_input": {
                    "input_data": {"task": target, "analysis_task": task},
                    "echo": True,
                    "max_iterations": self.max_iterations,
                    "resume": self.resume,
                },
                "agent_kwargs": {
                    "use_llm_name": os.getenv("DS_MODEL_NAME") or self._first_model_name(),
                    "use_vlm_name": os.getenv("VLM_MODEL_NAME") or self._first_model_name(),
                    "use_embedding_name": os.getenv("EMBEDDING_MODEL_NAME") or self._first_model_name(),
                },
                "priority": 2,
                "task": task,
            }
            for task in state.get("analysis_tasks", [])
        ]
        ids, errors = await self._run_agent_specs(specs, "analyze")
        return self._phase_result(state, "analyze", ids, errors, "analyzer_agent_ids")

    async def generate_report(self, state: ResearchState) -> dict[str, Any]:
        await self._emit("phase_start", phase="report")
        spec = {
            "agent_class": ReportGenerator,
            "task_input": {
                "input_data": {"task": self._research_target(), "task_type": state.get("target_type", "company")},
                "echo": True,
                "max_iterations": self.max_iterations,
                "resume": self.resume,
            },
            "agent_kwargs": {
                "use_llm_name": os.getenv("DS_MODEL_NAME") or self._first_model_name(),
                "use_embedding_name": os.getenv("EMBEDDING_MODEL_NAME") or self._first_model_name(),
            },
            "priority": 3,
            "task": "Final report generation",
        }
        ids, errors = await self._run_agent_specs([spec], "report")
        artifacts = self._artifact_paths()
        result = self._phase_result(state, "report", ids, errors, "report_agent_id")
        result["report_agent_id"] = ids[0] if ids else ""
        result["artifact_paths"] = artifacts
        return result

    async def audit(self, state: ResearchState) -> dict[str, Any]:
        await self._emit("phase_start", phase="audit")
        warnings = list(state.get("warnings", []))
        errors = list(state.get("errors", []))
        evidence = self.memory.knowledge_state.get("evidence", {}) if self.memory.knowledge_state else {}
        audit_files = [Path(path) for path in state.get("artifact_paths", []) if path.endswith(".knowledge.json")]
        unresolved = 0
        for path in audit_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                unresolved += sum(item.get("status") != "resolved" for item in payload.get("citations", []))
            except Exception as exc:
                errors.append({"phase": "audit", "type": type(exc).__name__, "message": str(exc)})
        if knowledge_settings(self.config)["enabled"] and not evidence:
            warnings.append("Knowledge mode was enabled but the final task contains no registered evidence.")
        if unresolved:
            warnings.append(f"Citation audit contains {unresolved} unresolved reference(s).")
        await self._emit("phase_complete", phase="audit", unresolved_citations=unresolved)
        return {
            "phase": "audit",
            "errors": errors,
            "warnings": warnings,
            "evidence_ids": list(evidence),
            "metrics": {
                "collect_tasks": len(state.get("collect_tasks", [])),
                "analysis_tasks": len(state.get("analysis_tasks", [])),
                "evidence": len(evidence),
                "unresolved_citations": unresolved,
            },
        }

    async def finalize(self, state: ResearchState) -> dict[str, Any]:
        self.memory.save()
        errors = state.get("errors", [])
        warnings = state.get("warnings", [])
        if errors and self.fail_fast:
            status = "failed"
        elif errors or warnings:
            status = "completed_with_warnings"
        else:
            status = "completed"
        await self._emit("workflow_complete", status=status, metrics=state.get("metrics", {}))
        return {"phase": "complete", "status": status, "completed_at": _utc_now()}

    def build(self, checkpointer: BaseCheckpointSaver | None = None):
        builder = StateGraph(ResearchState)
        builder.add_node("initialize", self.initialize)
        builder.add_node("plan", self.plan)
        builder.add_node("retrieve", self.retrieve_initial_evidence)
        builder.add_node("assess_evidence", self.assess_evidence)
        builder.add_node("expand_retrieval", self.expand_retrieval)
        builder.add_node("collect", self.collect)
        builder.add_node("analyze", self.analyze)
        builder.add_node("report", self.generate_report)
        builder.add_node("audit", self.audit)
        builder.add_node("finalize", self.finalize)
        builder.add_edge(START, "initialize")
        builder.add_edge("initialize", "plan")
        builder.add_edge("plan", "retrieve")
        builder.add_edge("retrieve", "assess_evidence")
        builder.add_conditional_edges(
            "assess_evidence",
            self.route_after_evidence,
            {"expand": "expand_retrieval", "continue": "collect"},
        )
        builder.add_edge("expand_retrieval", "assess_evidence")
        builder.add_edge("collect", "analyze")
        builder.add_edge("analyze", "report")
        builder.add_edge("report", "audit")
        builder.add_edge("audit", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=checkpointer, name="financial_research")

    def initial_state(self, task_id: str) -> ResearchState:
        return {
            "task_id": task_id,
            "research_query": self._research_target(),
            "target_name": self.config.config.get("target_name", ""),
            "stock_code": self.config.config.get("stock_code", ""),
            "target_type": self.config.config.get("target_type", "company"),
            "resume": self.resume,
            "phase": "pending",
            "status": "pending",
            "collect_tasks": [],
            "analysis_tasks": [],
            "collector_agent_ids": [],
            "analyzer_agent_ids": [],
            "report_agent_id": "",
            "evidence_ids": [],
            "retrieval_queries": [],
            "retrieval_rounds": 0,
            "artifact_paths": [],
            "errors": [],
            "warnings": [],
            "metrics": {},
            "started_at": _utc_now(),
        }

    async def _run_agent_specs(self, specs: list[dict[str, Any]], phase: str) -> tuple[list[str], list[dict[str, str]]]:
        agents = []
        for spec in specs:
            agent = await self.memory.get_or_create_agent(
                agent_class=spec["agent_class"],
                task_input=spec["task_input"],
                resume=self.resume,
                priority=spec["priority"],
                **spec["agent_kwargs"],
            )
            agents.append((agent, spec))
        self.memory.save()
        semaphore = asyncio.Semaphore(self.max_concurrent) if self.max_concurrent else None

        async def run_one(agent: Any, spec: dict[str, Any]):
            if self.resume and self.memory.is_agent_finished(agent.id):
                await self._emit("agent_skipped", phase=phase, agent_id=agent.id, task=spec["task"])
                return None
            await self._emit("agent_start", phase=phase, agent_id=agent.id, agent_type=agent.AGENT_NAME, task=spec["task"])
            if semaphore:
                async with semaphore:
                    result = await agent.async_run(**spec["task_input"])
            else:
                result = await agent.async_run(**spec["task_input"])
            await self._emit("agent_complete", phase=phase, agent_id=agent.id, agent_type=agent.AGENT_NAME)
            return result

        results = await asyncio.gather(*(run_one(agent, spec) for agent, spec in agents), return_exceptions=True)
        errors = []
        for (agent, _), result in zip(agents, results):
            if isinstance(result, BaseException):
                errors.append({
                    "phase": phase,
                    "agent_id": agent.id,
                    "type": type(result).__name__,
                    "message": str(result),
                    "traceback": "".join(traceback.format_exception(type(result), result, result.__traceback__)),
                })
                await self._emit("agent_error", phase=phase, agent_id=agent.id, error=str(result))
        if errors and self.fail_fast:
            raise RuntimeError(f"{phase} phase failed: {errors[0]['message']}")
        await self._emit("phase_complete", phase=phase, agent_count=len(agents), error_count=len(errors))
        return [agent.id for agent, _ in agents], errors

    @staticmethod
    def _phase_result(state: ResearchState, phase: str, ids: list[str], errors: list[dict[str, str]], id_key: str) -> dict[str, Any]:
        result: dict[str, Any] = {"phase": phase, "errors": list(state.get("errors", [])) + errors}
        result[id_key] = ids
        return result

    def _artifact_paths(self) -> list[str]:
        root = Path(self.config.working_dir)
        suffixes = {".md", ".docx", ".pdf", ".json"}
        return sorted(str(path.resolve()) for path in root.iterdir() if path.is_file() and path.suffix.lower() in suffixes)

    def _first_model_name(self) -> str:
        if not self.config.llm_dict:
            raise ValueError("At least one LLM must be configured for the research workflow")
        return next(iter(self.config.llm_dict))

    def _research_target(self) -> str:
        return (
            f"Research target: {self.config.config.get('target_name', '')} "
            f"(ticker: {self.config.config.get('stock_code', '')}), "
            f"target type: {self.config.config.get('target_type', 'company')}"
        )


def default_thread_id(config: Any, config_path: str = "") -> str:
    identity = f"{Path(config_path).resolve() if config_path else ''}:{config.config.get('target_name')}:{config.config.get('stock_code')}"
    prefix = str(config.config.get("target_name", "research"))[:32]
    return f"{prefix}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"


async def run_research_graph(
    config: Any,
    *,
    resume: bool = True,
    max_concurrent: int | None = None,
    thread_id: str | None = None,
    config_path: str = "",
    status_callback: StatusCallback | None = None,
) -> ResearchState:
    """Compile and execute the graph with a durable SQLite checkpointer."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    workflow = config.config.get("workflow", {})
    checkpoint_path = workflow.get("checkpoint_db") or str(Path(config.working_dir) / "workflow_checkpoints.sqlite3")
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    base_thread_id = thread_id or workflow.get("thread_id") or default_thread_id(config, config_path)
    effective_thread_id = base_thread_id if resume else f"{base_thread_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    runner = ResearchGraphRunner(
        config,
        resume=resume,
        max_concurrent=max_concurrent,
        status_callback=status_callback,
    )
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        graph = runner.build(checkpointer=checkpointer)
        result = await graph.ainvoke(
            runner.initial_state(effective_thread_id),
            config={"configurable": {"thread_id": effective_thread_id}},
        )
    return result
