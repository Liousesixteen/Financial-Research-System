import React, { useEffect, useState } from 'react'
import { Alert, Card, Form, Input, Select, Switch } from 'antd'
import { DatabaseOutlined } from '@ant-design/icons'
import { listKnowledgeLibraries } from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'

export default function KnowledgeSettings() {
    const { language } = useLanguage()
    const c = (zh, en) => language === 'zh' ? zh : en
    const [libraries, setLibraries] = useState([])
    const [error, setError] = useState('')
    useEffect(() => { listKnowledgeLibraries().then(r => setLibraries(r.data.libraries)).catch(e => setError(e.message)) }, [])
    return <Card title={<><DatabaseOutlined /> {c('知识库与证据', 'Knowledge and evidence')}</>} style={{ marginBottom: 16 }}>
        {error && <Alert type="warning" message={error} />}
        <Form.Item name={['knowledge_base', 'enabled']} valuePropName="checked" label={c('启用知识库', 'Enable knowledge library')}><Switch /></Form.Item>
        <Form.Item name={['knowledge_base', 'kb_ids']} label={c('用于本次研究的资料库', 'Libraries for this research')}><Select mode="multiple" placeholder={c('选择资料库', 'Select libraries')} options={libraries.map(l => ({ value: l.id, label: l.name }))} /></Form.Item>
        <Form.Item name={['knowledge_base', 'mode']} label={c('研究模式', 'Research mode')}><Select options={[{ value: 'hybrid', label: c('知识库 + 联网', 'Knowledge + web') }, { value: 'knowledge_only', label: c('仅知识库（文字研究）', 'Knowledge only (text research)') }]} /></Form.Item>
        <Form.Item name={['knowledge_base', 'as_of']} label={c('研究截止日期（可选）', 'Research cutoff (optional)')}><Input type="date" /></Form.Item>
        <Form.Item name={['knowledge_base', 'vector_backend']} label={c('向量存储', 'Vector backend')}><Select options={[{ value: 'local', label: c('本地（无需独立服务）', 'Local (no server required)') }, { value: 'qdrant', label: 'Qdrant' }]} /></Form.Item>
        <Form.Item name={['knowledge_base', 'qdrant_url']} label="Qdrant URL"><Input placeholder="http://localhost:6333" /></Form.Item>
        <Alert type="info" showIcon message={c('仅知识库模式禁用联网工具和生成的 Python，不生成分析图表；模型仍使用你配置的服务。恢复执行保留原资料快照，更新资料后请开始新的研究。', 'Knowledge-only disables external tools and generated Python/charts. Your configured model is still used. Resuming preserves the original evidence snapshot; start a fresh run to use new documents.')} />
    </Card>
}
