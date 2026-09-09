"""Real agent/memory/reference paths with a deterministic model, no API spend."""
from types import SimpleNamespace
import pytest
from src.knowledge.service import KnowledgeBaseService
from src.knowledge.runtime import initialize_session
from src.agents.base_agent import BaseAgent
from src.agents.report_generator.report_generator import ReportGenerator
from src.agents.report_generator.report_class import Report
from src.memory import Memory
from src.config import Config


class DeterministicModel:
    def __init__(self): self.messages = []
    async def generate(self, messages, **kwargs):
        self.messages = list(messages)
        if not any(m['content'] == '<knowledge_search>margin</knowledge_search>' for m in messages):
            return '<knowledge_search>margin</knowledge_search>'
        import re
        evidence = re.search(r'\[KB:([a-f0-9]{32})\]', '\n'.join(m['content'] for m in messages)).group(1)
        return f'<final_result>Margin increased [KB:{evidence}]</final_result>'


class EvidenceAgent(BaseAgent):
    AGENT_NAME = 'knowledge_test'
    NECESSARY_KEYS = ['task']
    def _set_default_tools(self): self.tools = []
    async def _prepare_executor(self): pass
    async def _prepare_init_prompt(self, input_data):
        return [{'role': 'user', 'content': 'Research margin.'}]


@pytest.mark.asyncio
async def test_agent_retrieval_memory_roundtrip_and_report_reference(tmp_path):
    service = KnowledgeBaseService(tmp_path / 'kb'); library = service.create_library('test')['id']
    entry = service.enqueue(library, 'source.txt', b'margin increased from 10% to 12%', {'published_at': '2025-01-01'})
    await service.process(entry['job_id'])
    model = DeterministicModel()
    config = SimpleNamespace(working_dir=str(tmp_path / 'run'), config={'working_dir': str(tmp_path / 'run'), 'target_type': 'general',
        'knowledge_base': {'enabled': True, 'kb_ids': [library], 'mode': 'knowledge_only', 'storage_dir': str(tmp_path / 'kb')}}, llm_dict={'test': model})
    memory = Memory(config); initialize_session(memory)
    agent = EvidenceAgent(config, tools=[], enable_code=False, memory=memory, use_llm_name='test')
    result = await agent.async_run({'task': 'Explain margin'}, max_iterations=3)
    assert '[KB:' in result['final_result']
    restored = Memory(config); assert restored.load()
    assert restored.knowledge_state['evidence']
    blocked = await agent._handle_code_action("raise Exception('must not execute')")
    assert 'disabled' in blocked['result']
    report = Report('# Research\n\n## Findings'); report.title = 'research'
    report.sections[0].set_content(result['final_result'])
    generator = ReportGenerator.__new__(ReportGenerator); generator.memory = restored; generator.config = config
    await generator._add_reference(report)
    assert '[1]' in report.content and 'paragraph 1' in report.content
    assert (tmp_path / 'run' / 'research.knowledge.json').exists()
    config.config['knowledge_base']['as_of'] = '2024-01-01'
    with pytest.raises(ValueError, match='changed'): Memory(config).load()


def test_web_config_without_environment_and_nested_merge(tmp_path, monkeypatch):
    for name in ('DS_MODEL_NAME', 'DS_API_KEY', 'DS_BASE_URL', 'VLM_MODEL_NAME', 'VLM_API_KEY', 'VLM_BASE_URL', 'EMBEDDING_MODEL_NAME', 'EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL'):
        monkeypatch.delenv(name, raising=False)
    config = Config(config_dict={'target_name': 'test', 'output_dir': str(tmp_path), 'llm_config_list': [], 'knowledge_base': {'top_k': 4}})
    assert config.config['knowledge_base']['enabled'] is False
    assert config.config['knowledge_base']['top_k'] == 4
    assert not config.llm_dict


def test_full_backend_cors_and_knowledge_config_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import demo.backend.app as backend
    monkeypatch.setattr(backend, 'current_config', None)
    monkeypatch.setenv('FRS_KB_DIR', str(tmp_path / 'kb'))
    with TestClient(backend.app) as client:
        response = client.options('/api/knowledge/libraries', headers={
            'Origin': 'http://127.0.0.1:3000', 'Access-Control-Request-Method': 'POST'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'http://127.0.0.1:3000'
        library = client.post('/api/knowledge/libraries', json={'name': 'test'}) .json()['id']
        payload = {'target_name': 'demo', 'stock_code': 'DEMO', 'output_dir': str(tmp_path / 'reports'),
                   'llm_configs': [], 'ds_model_name': 'test', 'vlm_model_name': 'test', 'embedding_model_name': 'test',
                   'knowledge_base': {'enabled': True, 'kb_ids': [library], 'mode': 'knowledge_only', 'as_of': '2025-12-31'}}
        assert client.post('/api/config', json=payload).status_code == 200
        restored = client.get('/api/config').json()['config']['knowledge_base']
        assert restored['kb_ids'] == [library] and restored['as_of'] == '2025-12-31'
        assert backend.knowledge_service().root == (tmp_path / 'kb').resolve()
