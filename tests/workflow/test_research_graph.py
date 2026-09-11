from types import SimpleNamespace

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.workflow.research_graph import ResearchGraphRunner


class DeterministicGraphRunner(ResearchGraphRunner):
    def __init__(self, tmp_path):
        self.resume = False
        self.config = SimpleNamespace(
            working_dir=str(tmp_path),
            config={"target_name": "Demo", "stock_code": "DEMO", "target_type": "financial_company"},
        )

    async def initialize(self, state):
        return {"phase": "initialize", "status": "running"}

    async def plan(self, state):
        return {"phase": "plan", "collect_tasks": ["prices"], "analysis_tasks": ["valuation"]}

    async def retrieve_initial_evidence(self, state):
        return {"phase": "retrieve", "evidence_ids": ["evidence-1"]}

    async def assess_evidence(self, state):
        return {"phase": "assess_evidence"}

    async def collect(self, state):
        assert state["collect_tasks"] == ["prices"]
        return {"phase": "collect", "collector_agent_ids": ["collector-1"]}

    async def analyze(self, state):
        assert state["collector_agent_ids"] == ["collector-1"]
        return {"phase": "analyze", "analyzer_agent_ids": ["analyzer-1"]}

    async def generate_report(self, state):
        assert state["analyzer_agent_ids"] == ["analyzer-1"]
        return {"phase": "report", "report_agent_id": "report-1", "artifact_paths": ["report.md"]}

    async def audit(self, state):
        return {"phase": "audit", "metrics": {"evidence": len(state["evidence_ids"])}}

    async def finalize(self, state):
        return {"phase": "complete", "status": "completed", "completed_at": "now"}


@pytest.mark.asyncio
async def test_graph_runs_research_phases_in_dependency_order(tmp_path):
    runner = DeterministicGraphRunner(tmp_path)
    result = await runner.build().ainvoke(runner.initial_state("research-1"))

    assert result["status"] == "completed"
    assert result["collector_agent_ids"] == ["collector-1"]
    assert result["analyzer_agent_ids"] == ["analyzer-1"]
    assert result["report_agent_id"] == "report-1"
    assert result["metrics"] == {"evidence": 1}


@pytest.mark.asyncio
async def test_graph_persists_serializable_state_in_sqlite(tmp_path):
    runner = DeterministicGraphRunner(tmp_path)
    checkpoint_db = tmp_path / "workflow.sqlite3"
    config = {"configurable": {"thread_id": "research-checkpoint"}}

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as checkpointer:
        graph = runner.build(checkpointer=checkpointer)
        await graph.ainvoke(runner.initial_state("research-checkpoint"), config=config)
        snapshot = await graph.aget_state(config)

    assert snapshot.values["status"] == "completed"
    assert snapshot.values["evidence_ids"] == ["evidence-1"]
    assert checkpoint_db.exists() and checkpoint_db.stat().st_size > 0


def test_evidence_gate_expands_sparse_knowledge_results(tmp_path):
    runner = DeterministicGraphRunner(tmp_path)
    runner.config.config["knowledge_base"] = {"enabled": True}
    runner.min_initial_evidence = 3
    runner.max_retrieval_rounds = 1

    assert runner.route_after_evidence({"evidence_ids": [], "retrieval_rounds": 0}) == "expand"
    assert runner.route_after_evidence({"evidence_ids": ["1", "2", "3"], "retrieval_rounds": 0}) == "continue"
    assert runner.route_after_evidence({"evidence_ids": [], "retrieval_rounds": 1}) == "continue"
