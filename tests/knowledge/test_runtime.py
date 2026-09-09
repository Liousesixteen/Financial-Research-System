from types import SimpleNamespace
import pytest
from src.knowledge.runtime import initialize_session, evidence_context, preserve_citations, resolve_references, only_knowledge
from src.knowledge.service import KnowledgeBaseService


@pytest.mark.asyncio
async def test_session_pins_evidence_and_rejects_changed_settings(tmp_path):
    service = KnowledgeBaseService(tmp_path)
    kb = service.create_library('A')['id']
    item = service.enqueue(kb, 'source.txt', b'margin rose by 5 percent', {'published_at': '2025-01-01'})
    await service.process(item['job_id'])
    config = SimpleNamespace(config={'knowledge_base': {'enabled': True, 'kb_ids': [kb], 'storage_dir': str(tmp_path), 'mode': 'knowledge_only'}}, llm_dict={})
    memory = SimpleNamespace(config=config, save=lambda: None)
    initialize_session(memory)
    service.delete_document(item['doc_id'])
    context = await evidence_context(memory, 'margin')
    assert '[KB:' in context and 'margin rose' in context and only_knowledge(config)
    assert len(memory.knowledge_state['evidence']) == 1
    config.config['knowledge_base']['as_of'] = '2025-01-01'
    with pytest.raises(ValueError, match='changed'): await evidence_context(memory, 'margin')


@pytest.mark.asyncio
async def test_disabled_needs_no_storage_or_models():
    memory = SimpleNamespace(config=SimpleNamespace(config={}, llm_dict={}))
    assert await evidence_context(memory, 'anything') == ''


def test_deterministic_citations_unknown_id_and_no_nearest_guess():
    report = SimpleNamespace(sections=[SimpleNamespace(_content=['A [KB:good]. B [KB:missing]. C [KB:good]. D [Source: approximate].'])])
    evidence = {'good': {'title': 'Annual Report', 'locator': 'PDF p.42', 'version': 'abcdef123456xyz', 'metadata': {'published_at': '2025-01-01'}}}
    refs, audit = resolve_references(report, evidence)
    assert report.sections[0]._content[0].count('[1]') == 2
    assert 'p.42' in refs
    assert sum(a['status'] == 'unverified' for a in audit) == 2


def test_polish_must_preserve_citations():
    draft = 'Margin rose [KB:abc]'
    assert preserve_citations(draft, 'Margin rose') == draft
    assert preserve_citations(draft, 'Improved [KB:abc]') == 'Improved [KB:abc]'
