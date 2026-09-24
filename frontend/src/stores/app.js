import { defineStore } from 'pinia'
import http from '@/api/http'

// 多租户 UI（BASE-07/08）：
// - 数据按当前用户 JWT 中的 tenant 行级过滤（BFF 强制，前端无法越权）
// - 「租户切换」对平台管理员（有 iam:manage，可跨租户）：切换目标租户后调用 /api/tenants 选择 +
//   重新以该租户登录。对普通用户：只显示自己所属租户（隔离视图）。
// - 普通用户的隔离视图：所有列表/详情天然只返回本租户数据（BFF 行级过滤），前端无需额外过滤。
export const useAppStore = defineStore('app', {
  state: () => ({
    // 当前租户 code（来自登录时填写的 tenant_code，JWT claims 的 tenant_id 为权威）
    currentTenant: null,
    tenantName: null,
    // 平台管理员可见的租户列表（租户管理页用）
    tenants: [],
    sidebarCollapsed: false,
  }),
  getters: {
    isPlatformAdmin: (s) => false, // 由 auth.scopes 动态判断（hasScope('iam:manage')）
  },
  actions: {
    setTenant(code, name) {
      this.currentTenant = code
      this.currentTenantName = name || code
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    async fetchTenants(params = {}) {
      const res = await http.get('/api/tenants', { params: { page: 1, page_size: 200, ...params } })
      this.tenants = res.data?.items ?? []
      return this.tenants
    },
  },
})
