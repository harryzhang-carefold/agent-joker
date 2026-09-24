import http from './http'

// iam（BASE-01/02/03）：用户 / 角色 / scope / 租户
export const listUsers = (params) => http.get('/api/users', { params })
export const createUser = (body) => http.post('/api/users', body)
export const getUser = (id) => http.get(`/api/users/${id}`)
export const updateUser = (id, body) => http.put(`/api/users/${id}`, body)
export const deleteUser = (id) => http.delete(`/api/users/${id}`)
export const resetPassword = (id, body) => http.post(`/api/users/${id}/reset-password`, body)

export const listRoles = () => http.get('/api/roles')
export const createRole = (body) => http.post('/api/roles', body)
export const updateRole = (id, body) => http.put(`/api/roles/${id}`, body)
export const deleteRole = (id) => http.delete(`/api/roles/${id}`)

export const listScopes = () => http.get('/api/scopes')
export const createScope = (body) => http.post('/api/scopes', body)

// tenants（平台管理视角，iam:manage；S17/BUG-07：仅平台管理员（system 租户）可用）
export const listTenants = (params, config) => http.get('/api/tenants', { params, ...config })
export const createTenant = (body) => http.post('/api/tenants', body)
export const updateTenant = (id, body) => http.put(`/api/tenants/${id}`, body)

// audit（BASE-06，scope trace:read）
export const listAuditLogs = (params) => http.get('/api/audit/logs', { params })
