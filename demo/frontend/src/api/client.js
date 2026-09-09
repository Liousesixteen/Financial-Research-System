import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const client = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
})

// Config APIs
export const getConfig = () => client.get('/api/config')
export const listConfigs = () => client.get('/api/config/list')
export const updateConfig = (config) => client.post('/api/config', config)
export const saveConfig = (name) => client.post('/api/config/save', { name })
export const loadConfig = (name) => client.post('/api/config/load', { name })
export const deleteConfig = (name) => client.delete(`/api/config/${name}`)

// Tasks APIs
export const getTasks = () => client.get('/api/tasks')
export const listTaskConfigs = () => client.get('/api/tasks/list')
export const updateTasks = (tasks) => client.post('/api/tasks', tasks)
export const saveTasks = (name) => client.post('/api/tasks/save', { name })
export const loadTasks = (name) => client.post('/api/tasks/load', { name })
export const deleteTaskConfig = (name) => client.delete(`/api/tasks/${name}`)

// Execution APIs
export const getExecutionStatus = () => client.get('/api/execution/status')
export const startExecution = (resume = false) =>
    client.post('/api/execution/start', { resume })
export const stopExecution = () => client.post('/api/execution/stop')
export const getLastExecution = () => client.get('/api/execution/last')

// Reports APIs
export const listReports = () => client.get('/api/reports')
export const getReportPreview = (targetName, filename) =>
    client.get(`/api/reports/preview/${encodeURIComponent(targetName)}/${encodeURIComponent(filename)}`)
export const getReportDownloadUrl = (targetName, filename) =>
    `${API_BASE_URL}/api/reports/download/${encodeURIComponent(targetName)}/${encodeURIComponent(filename)}`

// WebSocket connection
export const createWebSocketConnection = (onMessage, onError, onClose) => {
    const wsUrl = API_BASE_URL.replace('http', 'ws') + '/ws/logs'
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
        console.log('WebSocket connected')
    }

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (onMessage) onMessage(data)
    }

    ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        if (onError) onError(error)
    }

    ws.onclose = () => {
        console.log('WebSocket disconnected')
        if (onClose) onClose()
    }

    return ws
}

export default client


// Persistent knowledge library
export const listKnowledgeLibraries = () => client.get('/api/knowledge/libraries')
export const createKnowledgeLibrary = (name) => client.post('/api/knowledge/libraries', { name })
export const renameKnowledgeLibrary = (id, name) => client.patch(`/api/knowledge/libraries/${id}`, { name })
export const listKnowledgeDocuments = (id) => client.get(`/api/knowledge/libraries/${id}/documents`)
export const uploadKnowledgeDocument = (id, file, metadata) => {
    const data = new FormData()
    data.append('file', file)
    data.append('metadata', JSON.stringify(metadata))
    return client.post(`/api/knowledge/libraries/${id}/documents`, data, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const getKnowledgeDocument = (id) => client.get(`/api/knowledge/documents/${id}`)
export const deleteKnowledgeDocument = (id) => client.delete(`/api/knowledge/documents/${id}`)
export const reindexKnowledgeDocument = (id) => client.post(`/api/knowledge/documents/${id}/reindex`)
export const searchKnowledge = (data) => client.post('/api/knowledge/search', data)
export const knowledgeOriginalUrl = (id, page) => `${API_BASE_URL}/api/knowledge/documents/${id}/original${page ? `#page=${page}` : ''}`
