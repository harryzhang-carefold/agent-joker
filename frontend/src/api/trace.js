import http from './http'

// trace（TRACE-01/02，scope trace:read）：会话 / 事件 / 多维检索
export const listTraceSessions = (params) => http.get('/api/trace/sessions', { params })
export const getTraceSession = (sid) => http.get(`/api/trace/sessions/${sid}`)
export const listTraceEvents = (sid, params) =>
  http.get(`/api/trace/sessions/${sid}/events`, { params })
export const searchEvents = (params) => http.get('/api/trace/events', { params })
