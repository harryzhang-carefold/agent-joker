import { defineStore } from 'pinia'

// 认证状态 + JWT 双令牌（DECISION-002）：
// - access 15min 存内存 + localStorage（便于刷新页面恢复）
// - refresh 7d 存 localStorage，自动续期（refresh 轮换）
// - 登出：调 /api/auth/logout（吊销 refresh + access jti 黑名单）+ 清空本地
const LS_ACCESS = 'joker.access'
const LS_REFRESH = 'joker.refresh'
const LS_USER = 'joker.user'

function readUser() {
  try {
    const raw = localStorage.getItem(LS_USER)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(LS_ACCESS) || null,
    refreshToken: localStorage.getItem(LS_REFRESH) || null,
    user: readUser(),
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken,
    tenantCode: (s) => (s.user && s.user.tenant_code) || null,
    scopes: (s) => (s.user && s.user.scopes) || [],
    hasScope: (s) => (name) => (s.scopes || []).includes(name),
  },
  actions: {
    setTokens({ access_token, refresh_token, user }) {
      this.accessToken = access_token
      this.refreshToken = refresh_token
      if (user) this.user = user
      localStorage.setItem(LS_ACCESS, access_token)
      if (refresh_token) localStorage.setItem(LS_REFRESH, refresh_token)
      if (user) localStorage.setItem(LS_USER, JSON.stringify(user))
    },
    // 无感续期：用 refresh 换新 access+refresh（轮换）。仅调用一次（避免并发重复）
    async refreshAccessToken() {
      if (!this.refreshToken) throw new Error('no refresh token')
      if (this._refreshing) return this._refreshing
      this._refreshing = (async () => {
        const res = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        })
        if (!res.ok) {
          this.clear()
          throw new Error('refresh failed: ' + res.status)
        }
        const data = await res.json()
        this.setTokens({
          access_token: data.access_token,
          refresh_token: data.refresh_token,
        })
        return data
      })()
      try {
        return await this._refreshing
      } finally {
        this._refreshing = null
      }
    },
    async logout() {
      try {
        if (this.accessToken) {
          await fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${this.accessToken}`,
            },
            body: JSON.stringify({ refresh_token: this.refreshToken || undefined }),
          })
        }
      } catch {
        /* 登出尽力而为，即使接口失败也清本地 */
      }
      this.clear()
    },
    clear() {
      this.accessToken = null
      this.refreshToken = null
      this.user = null
      localStorage.removeItem(LS_ACCESS)
      localStorage.removeItem(LS_REFRESH)
      localStorage.removeItem(LS_USER)
    },
    // 页面刷新后：从持久化的 access token 重新解码 scopes（UI 权限菜单用）。
    // 若 user 无 scopes（刷新后丢失）则补上。
    hydrateFromToken() {
      if (!this.accessToken) return
      const payload = this.accessToken.split('.')[1]
      const b64 = payload.replace(/-/g, '+').replace(/_/g, '/')
      const pad = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
      try {
        const json = decodeURIComponent(
          atob(pad)
            .split('')
            .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
            .join('')
        )
        const claims = JSON.parse(json)
        this.user = this.user || {}
        this.user.scopes = claims.scopes || this.user.scopes || []
        this.user.tenant_id = claims.tenant_id || this.user.tenant_id
        this.user.user_id = claims.user_id || this.user.user_id
        localStorage.setItem(LS_USER, JSON.stringify(this.user))
      } catch {
        /* token 损坏由请求拦截器后续刷新/登出处理 */
      }
    },
  },
})
