import http from './http'

// agents（AGENT-01..11）：元数据 / 对话 / 会话 / 记忆
export const listAgents = (params) => http.get('/api/agents', { params })
export const getAgent = (id) => http.get(`/api/agents/${id}`)
export const createAgent = (body) => http.post('/api/agents', body)
export const updateAgent = (id, body) => http.put(`/api/agents/${id}`, body)
export const deleteAgent = (id) => http.delete(`/api/agents/${id}`)

// 对话（块式，/api/agents/{id}/chat）
export const agentChat = (id, body) => http.post(`/api/agents/${id}/chat`, body)

// 会话
export const listSessions = (agentId, params) =>
  http.get(`/api/agents/${agentId}/sessions`, { params })
export const getMessages = (agentId, sessionId) =>
  http.get(`/api/agents/${agentId}/sessions/${sessionId}/messages`)
export const createSession = (agentId) => http.post(`/api/agents/${agentId}/sessions`)
export const renameSession = (agentId, sessionId, title) =>
  http.patch(`/api/agents/${agentId}/sessions/${sessionId}`, { title })
export const closeSession = (agentId, sessionId) =>
  http.post(`/api/agents/${agentId}/sessions/${sessionId}/close`)
export const deleteSession = (agentId, sessionId) =>
  http.delete(`/api/agents/${agentId}/sessions/${sessionId}`)

// 记忆 / 笔记
export const listMemories = (agentId, limit = 50) =>
  http.get(`/api/agents/${agentId}/memories`, { params: { limit } })
export const listNotes = (agentId, limit = 50) =>
  http.get(`/api/agents/${agentId}/notes`, { params: { limit } })
