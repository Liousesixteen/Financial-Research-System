import React, { useEffect, useRef, useState } from 'react'
import { Alert, Button, Drawer, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, Upload, message } from 'antd'
import { DatabaseOutlined, FileSearchOutlined, PlusOutlined, UploadOutlined, ReloadOutlined, EditOutlined, DeleteOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { listKnowledgeLibraries, createKnowledgeLibrary, renameKnowledgeLibrary, listKnowledgeDocuments, uploadKnowledgeDocument, getKnowledgeDocument, deleteKnowledgeDocument, reindexKnowledgeDocument, searchKnowledge, knowledgeOriginalUrl } from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'
import './knowledge.css'

export default function KnowledgePage() {
    const { language } = useLanguage()
    const c = (zh, en) => language === 'zh' ? zh : en
    const [libraries, setLibraries] = useState([])
    const [selected, setSelected] = useState('')
    const [documents, setDocuments] = useState([])
    const [loading, setLoading] = useState(false)
    const [query, setQuery] = useState('')
    const [results, setResults] = useState(null)
    const [searching, setSearching] = useState(false)
    const [filters, setFilters] = useState({})
    const [nameModal, setNameModal] = useState(null)
    const [name, setName] = useState('')
    const [uploadOpen, setUploadOpen] = useState(false)
    const [files, setFiles] = useState([])
    const [uploading, setUploading] = useState(false)
    const [preview, setPreview] = useState(null)
    const [form] = Form.useForm()
    const selection = useRef(selected)
    selection.current = selected
    const warningText = (w) => w === 'Embedding not configured; keyword search only' ? c('尚未配置向量模型，当前使用关键词检索。', w) : w.startsWith('Semantic search unavailable') ? c('语义检索暂不可用，已使用关键词检索。', w) : w === 'No eligible evidence' ? c('没有符合筛选条件的资料。', w) : w
    const showError = (e) => message.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message)
    const loadLibraries = async () => {
        try { const { data } = await listKnowledgeLibraries(); setLibraries(data.libraries); setSelected(prev => prev || data.libraries[0]?.id || '') }
        catch (e) { showError(e) }
    }
    const loadDocuments = async (id = selected, quiet = false) => {
        if (!id) return
        if (!quiet) setLoading(true)
        try { const { data } = await listKnowledgeDocuments(id); if (selection.current === id) setDocuments(data.documents) }
        catch (e) { if (!quiet) showError(e) }
        finally { if (!quiet) setLoading(false) }
    }
    useEffect(() => { loadLibraries() }, [])
    useEffect(() => { setDocuments([]); setResults(null); if (selected) loadDocuments(selected) }, [selected])
    useEffect(() => {
        if (!selected || !documents.some(d => ['queued', 'parsing', 'indexing'].includes(d.status))) return
        const timer = setInterval(() => loadDocuments(selected, true), 2500)
        return () => clearInterval(timer)
    }, [selected, documents])
    const saveName = async () => {
        if (!name.trim()) return
        try {
            if (nameModal === 'rename') await renameKnowledgeLibrary(selected, name.trim())
            else { const { data } = await createKnowledgeLibrary(name.trim()); setSelected(data.id) }
            setNameModal(null); setName(''); await loadLibraries()
        } catch (e) { showError(e) }
    }
    const upload = async () => {
        if (!files.length) return message.info(c('请先选择文件', 'Choose a file first'))
        const metadata = await form.validateFields()
        setUploading(true)
        try {
            let duplicates = 0
            for (const file of files) {
                const { data } = await uploadKnowledgeDocument(selected, file.originFileObj || file, metadata)
                if (data.duplicate) duplicates++
            }
            message.success(c(`已提交 ${files.length} 份资料，${duplicates} 份重复`, `Submitted ${files.length} files, ${duplicates} duplicates`))
            setFiles([]); setUploadOpen(false); await loadDocuments()
        } catch (e) { showError(e) }
        finally { setUploading(false) }
    }
    const search = async () => {
        if (!query.trim() || !selected) return
        setSearching(true)
        const id = selected
        try { const { data } = await searchKnowledge({ query, kb_ids: [id], filters }); if (selection.current === id) setResults(data) }
        catch (e) { showError(e) }
        finally { setSearching(false) }
    }
    const openDocument = async (id, chunkId) => {
        try { const { data } = await getKnowledgeDocument(id); setPreview({ ...data, chunkId }) }
        catch (e) { showError(e) }
    }
    const status = {
        ready: ['green', c('可检索', 'Ready')], queued: ['default', c('排队中', 'Queued')],
        parsing: ['blue', c('解析中', 'Parsing')], indexing: ['blue', c('索引中', 'Indexing')],
        failed: ['red', c('失败', 'Failed')], needs_ocr: ['orange', c('待 OCR', 'Needs OCR')],
    }
    const columns = [
        { title: c('文档 / 来源', 'Document / source'), dataIndex: 'title', render: (text, row) => <div><Button type="link" className="kb-document-link" onClick={() => openDocument(row.id)}>{text}</Button><div className="kb-muted">{row.filename} · {row.metadata.source_type || 'primary'} · {row.hash.slice(0, 8)}</div></div> },
        { title: c('研究标的', 'Entity'), render: (_, r) => <div>{r.metadata.company || '—'}<div className="kb-muted">{[r.metadata.market, r.metadata.ticker, r.metadata.industry].filter(Boolean).join(' · ')}</div></div> },
        { title: c('披露日 / 报告期', 'Published / period'), render: (_, r) => <div>{r.metadata.published_at || c('未标注', 'Unknown')}<div className="kb-muted">{r.metadata.report_period || '—'}</div></div> },
        { title: c('状态', 'Status'), dataIndex: 'status', render: (s, r) => <span title={r.error}><Tag color={status[s]?.[0]}>{status[s]?.[1] || s}</Tag>{r.error && <div className="kb-error">{r.error}</div>}</span> },
        { title: c('操作', 'Actions'), render: (_, r) => <Space><Button aria-label={c('重新索引', 'Reindex')} icon={<ReloadOutlined />} disabled={['queued', 'parsing', 'indexing'].includes(r.status)} onClick={async () => { try { await reindexKnowledgeDocument(r.id); await loadDocuments() } catch (e) { showError(e) } }} /><Popconfirm title={c('从检索中移除此文档？历史报告快照保留。', 'Remove from retrieval? Historical report snapshots remain.')} onConfirm={async () => { try { await deleteKnowledgeDocument(r.id); setResults(null); await loadDocuments() } catch (e) { showError(e) } }}><Button danger aria-label={c('删除文档', 'Delete document')} icon={<DeleteOutlined />} /></Popconfirm></Space> },
    ]
    return <div className="kb-workspace">
        <div className="kb-masthead"><div><div className="kb-eyebrow">FINANCIAL RESEARCH SYSTEM / RESEARCH LIBRARY</div><h1>{c('让研究有据可循', 'Research starts with evidence.')}</h1><p>{c('保存原始资料，检索关键证据，将每一个判断连接到来源。', 'Keep source documents, retrieve evidence, and trace every research claim.')}</p></div><div className="kb-count"><strong>{documents.filter(d => d.status === 'ready').length.toString().padStart(2, '0')}</strong><span>{c('可检索文档', 'indexed documents')}</span></div></div>
        <div className="kb-toolbar"><Space wrap><DatabaseOutlined /><Select aria-label={c('选择知识库', 'Select library')} style={{ minWidth: 220 }} placeholder={c('选择知识库', 'Select library')} value={selected || undefined} onChange={setSelected} options={libraries.map(l => ({ label: l.name, value: l.id }))} /><Button icon={<PlusOutlined />} onClick={() => { setName(''); setNameModal('create') }}>{c('新建', 'New')}</Button><Button aria-label={c('重命名知识库', 'Rename library')} disabled={!selected} icon={<EditOutlined />} onClick={() => { setName(libraries.find(l => l.id === selected)?.name || ''); setNameModal('rename') }} /></Space><Button type="primary" icon={<UploadOutlined />} disabled={!selected} onClick={() => setUploadOpen(true)}>{c('上传资料', 'Upload documents')}</Button></div>
        {!libraries.length ? <Empty description={c('创建第一个知识库，开始积累研究资料', 'Create your first research library')}><Button type="primary" onClick={() => setNameModal('create')}>{c('创建知识库', 'Create library')}</Button></Empty> : <>
            <section className="kb-search"><div className="kb-section-label">01 / {c('证据检索', 'EVIDENCE SEARCH')}</div><Input.Search size="large" aria-label={c('检索问题', 'Research question')} placeholder={c('例如：毛利率下降的原因是什么？', 'What caused the decline in gross margin?')} value={query} onChange={e => setQuery(e.target.value)} onSearch={search} loading={searching} enterButton={<><FileSearchOutlined /> {c('查找原文', 'Find evidence')}</>} /><div className="kb-filters">{[['company', '公司', 'Company'], ['ticker', '证券代码', 'Ticker'], ['market', '市场', 'Market'], ['industry', '行业', 'Industry'], ['report_period', '报告期', 'Period']].map(([key, zh, en]) => <Input key={key} aria-label={c(zh, en)} placeholder={c(zh, en)} value={filters[key] || ''} onChange={e => setFilters({ ...filters, [key]: e.target.value })} />)}<Input type="date" aria-label={c('研究截止日期', 'Research cutoff date')} value={filters.as_of || ''} onChange={e => setFilters({ ...filters, as_of: e.target.value })} /></div><div className="kb-muted">{c('筛选为精确匹配。截止日期按披露日过滤，未标注日期的资料将被排除。', 'Filters match exactly. A cutoff excludes later disclosures and documents without a publication date.')}</div>
                {results && <div className="kb-results"><Tag color={results.mode === 'hybrid' ? 'blue' : 'default'}>{results.mode === 'hybrid' ? c('混合检索', 'Hybrid search') : c('关键词检索', 'Keyword search')}</Tag>{results.warnings.map(w => <div key={w} className="kb-muted">{warningText(w)}</div>)}{!results.results.length ? <Empty description={c('没有找到符合条件的证据，试试其他关键词或筛选条件。', 'No matching evidence. Try another query or filter.')} /> : results.results.map((r, i) => <article className="kb-evidence" key={r.evidence_id}><div className="kb-evidence-number">{String(i + 1).padStart(2, '0')}</div><div><h3>{r.title}</h3><div className="kb-muted">{r.locator} · {r.metadata.published_at || c('日期未标注', 'Date unknown')} · {r.metadata.report_period}</div><p>{r.text}</p><Button type="link" onClick={() => openDocument(r.doc_id, r.id)}>{c('查看来源', 'Open source')} <ArrowRightOutlined /></Button></div></article>)}</div>}
            </section>
            <section><div className="kb-section-label kb-table-label">02 / {c('资料档案', 'DOCUMENT ARCHIVE')}<Button size="small" icon={<ReloadOutlined />} onClick={() => loadDocuments()}>{c('刷新', 'Refresh')}</Button></div><Table rowKey="id" dataSource={documents} columns={columns} loading={loading} pagination={{ pageSize: 8, hideOnSinglePage: true }} scroll={{ x: 850 }} locale={{ emptyText: c('上传年报、公告或研究材料。支持 PDF / DOCX / MD / TXT。', 'Upload annual reports, filings or research. PDF / DOCX / MD / TXT.') }} /></section>
        </>}
        <Modal title={nameModal === 'rename' ? c('重命名知识库', 'Rename library') : c('新建知识库', 'Create library')} open={!!nameModal} onCancel={() => setNameModal(null)} onOk={saveName} okButtonProps={{ disabled: !name.trim() }}><Input aria-label={c('知识库名称', 'Library name')} maxLength={100} value={name} onChange={e => setName(e.target.value)} onPressEnter={saveName} placeholder={c('例如：半导体行业研究', 'Semiconductor research')} /></Modal>
        <Modal title={c('上传研究资料', 'Upload research documents')} open={uploadOpen} onCancel={() => { if (!uploading) setUploadOpen(false) }} onOk={upload} confirmLoading={uploading} width={680} okText={c('上传并建立索引', 'Upload and index')}>
            <Alert type="info" showIcon message={c('支持文本型 PDF、DOCX、MD、TXT，单文件不超过 50 MB。扫描件需要 OCR。配置远程模型后，相关文本会发送到该模型服务。', 'Text PDFs, DOCX, MD and TXT up to 50 MB each. Scans need OCR. Configured remote models receive relevant document text.')} style={{ marginBottom: 16 }} />
            <Upload.Dragger multiple accept=".pdf,.docx,.md,.txt" fileList={files} beforeUpload={() => false} onChange={({ fileList }) => setFiles(fileList)} disabled={uploading}><UploadOutlined style={{ fontSize: 28, color: '#a52222' }} /><p>{c('拖入文件，或点击选择', 'Drop files here or click to select')}</p></Upload.Dragger>
            <Form form={form} layout="vertical" style={{ marginTop: 20 }} initialValues={{ source_type: 'primary' }}><div className="kb-form-grid">{[['company', '公司', 'Company'], ['ticker', '证券代码', 'Ticker'], ['market', '市场（A / HK / US）', 'Market (A / HK / US)'], ['industry', '行业', 'Industry'], ['published_at', '公开披露日期', 'Publication date'], ['report_period', '报告期', 'Reporting period']].map(([key, zh, en]) => <Form.Item key={key} name={key} label={c(zh, en)}><Input type={key === 'published_at' ? 'date' : 'text'} /></Form.Item>)}</div><Form.Item name="source_url" label={c('原始来源链接（可选）', 'Source URL (optional)')}><Input placeholder="https://" /></Form.Item><Form.Item name="source_type" label={c('来源类型', 'Source type')}><Select options={[{ value: 'primary', label: c('一手资料', 'Primary source') }, { value: 'research', label: c('研究材料', 'Research') }, { value: 'ai_generated', label: c('AI 生成（默认不检索）', 'AI generated (excluded by default)') }]} /></Form.Item></Form>
        </Modal>
        <Drawer title={preview?.document.title} open={!!preview} onClose={() => setPreview(null)} width="min(850px, 95vw)">{preview && <><Space wrap style={{ marginBottom: 20 }}><Tag>{preview.document.status}</Tag><Typography.Text type="secondary">{preview.document.filename}</Typography.Text><a href={knowledgeOriginalUrl(preview.document.id)} target="_blank" rel="noreferrer">{c('打开原文件', 'Open original')}</a></Space>{preview.document.error && <Alert type="warning" message={preview.document.error} />}{preview.chunks.map(chunk => <div key={chunk.id} className={`kb-source-block ${chunk.id === preview.chunkId ? 'kb-source-selected' : ''}`}><div className="kb-muted">{chunk.locator} · {chunk.kind}{chunk.page && <> · <a href={knowledgeOriginalUrl(preview.document.id, chunk.page)} target="_blank" rel="noreferrer">{c('打开此页', 'Open page')}</a></>}</div><pre>{chunk.text}</pre><Typography.Text code copyable>{`[KB:${chunk.id}]`}</Typography.Text></div>)}</>}</Drawer>
    </div>
}
