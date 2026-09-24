import http from './http'

// auth 端点（公开，不经 BFF 注入签名头）
export const login = (body) =>
  http.post('/api/auth/login', body, { silent: true })

export const refresh = (refresh_token) =>
  http.post('/api/auth/refresh', { refresh_token }, { silent: true })

export const logout = (refresh_token) =>
  http.post(
    '/api/auth/logout',
    { refresh_token },
    { headers: {} }
  )
