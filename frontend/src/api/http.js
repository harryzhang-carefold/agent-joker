import axios from 'axios'
import { ElMessage } from 'element-plus'

// S10 前端 HTTP 客户端（统一走 BFF /api、/v1、/mcp 前缀）。
// - 注入 Authorization: Bearer <access>（BFF 内部再做 X-Auth HMAC 签名，前端无需关心）
// - 401（access 过期/被登出）→ 用 refresh 无感续期一次 → 重试原请求；refresh 也失败 → 登出跳登录
// - 403/404 等不触发刷新（权限/租户隔离语义）
const http = axios.create({
  baseURL: '/',
  timeout: 120000,
  // 上传/流式超时放宽（原文档下载、文档上传、agent 对话）
})

let _refreshing = null

async function doRefresh() {
  // 直接走 auth store 的 refresh 逻辑（避免循环 import）
  const { useAuthStore } = await import('@/stores/auth')
  const auth = useAuthStore()
  if (!auth.refreshToken) throw new Error('no refresh token')
  return auth.refreshAccessToken()
}

async function getAccessToken() {
  const { useAuthStore } = await import('@/stores/auth')
  const auth = useAuthStore()
  if (!auth.accessToken) throw new Error('not logged in')
  return auth.accessToken
}

// 请求拦截：注入 token
http.interceptors.request.use(async (config) => {
  try {
    const token = await getAccessToken()
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  } catch (e) {
    // 未登录也允许放行（由响应拦截/路由守卫处理）
  }
  return config
})

// 响应拦截：401 → 无感刷新重试一次
http.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const original = error.config
    const status = error.response?.status
    // 仅对 401 且未重试过、非登录/刷新端点本身做刷新
    if (status === 401 && original && !original._retried) {
      const isAuthEndpoint = /\/api\/auth\//.test(original.url || '')
      if (!isAuthEndpoint) {
        original._retried = true
        try {
          _refreshing = _refreshing || doRefresh().finally(() => (_refreshing = null))
          await _refreshing
          const token = await getAccessToken()
          original.headers = original.headers || {}
          original.headers.Authorization = `Bearer ${token}`
          return http(original)
        } catch (e) {
          // refresh 失败 → 登出跳登录
          const { useAuthStore } = await import('@/stores/auth')
          const auth = useAuthStore()
          auth.clear()
          ElMessage.error('登录已失效，请重新登录')
          if (location.pathname !== '/login') {
            location.href = '/login'
          }
          return Promise.reject(e)
        }
      }
    }
    // 统一错误提示（detail 来自 FastAPI / BFF）
    const detail =
      error.response?.data?.detail || error.response?.statusText || error.message || '请求失败'
    if (!error.config?.silent) {
      ElMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    return Promise.reject(error)
  }
)

// 通用：分页列表解包（{items,total,page,page_size} → items）
export function unwrapList(data) {
  if (Array.isArray(data)) return { items: data, total: data.length }
  return { items: data?.items ?? [], total: data?.total ?? data?.items?.length ?? 0 }
}

export default http
