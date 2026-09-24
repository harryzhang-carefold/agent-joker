import http from './http'

// mcp（MCP-01/02/03）：server 注册 / 工具管理
const srv = (id) => `/api/mcp/servers/${id}`

export const listServers = (params) => http.get('/api/mcp/servers', { params })
export const getServer = (id) => http.get(srv(id))
export const createServer = (body) => http.post('/api/mcp/servers', body)
export const updateServer = (id, body) => http.put(srv(id), body)
export const deleteServer = (id, confirm = false) =>
  http.delete(srv(id), { params: { confirm } })
export const refreshServer = (id) => http.post(`${srv(id)}/refresh`)
export const referringAgentsOfServer = (id) =>
  http.get(`${srv(id)}/referring-agents`)

export const listTools = (serverId, params) =>
  http.get(`${srv(serverId)}/tools`, { params })
export const enableTool = (id) => http.post(`/api/mcp/tools/${id}/enable`)
export const disableTool = (id, confirm = false) =>
  http.post(`/api/mcp/tools/${id}/disable?confirm=${confirm}`)
export const deleteTool = (id, confirm = false) =>
  http.delete(`/api/mcp/tools/${id}`, { params: { confirm } })
export const referringAgentsOfTool = (id) =>
  http.get(`/api/mcp/tools/${id}/referring-agents`)
export const toolsCache = (serverId, refresh = false) =>
  http.get(`${srv(serverId)}/tools-cache`, { params: { refresh } })
