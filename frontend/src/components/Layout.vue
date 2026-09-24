<template>
  <el-container class="layout">
    <!-- 侧边栏 -->
    <el-aside :width="collapsed ? '64px' : '228px'" class="aside">
      <div class="logo">
        <span class="logo-icon">J</span>
        <span v-if="!collapsed" class="logo-text">agent-joker</span>
      </div>
      <el-scrollbar class="menu-scroll">
        <el-menu
          :default-active="activeMenu"
          :collapse="collapsed"
          background-color="transparent"
          text-color="#cbd5e1"
          active-text-color="#409eff"
          router
        >
          <el-sub-menu
            v-for="g in visibleGroups"
            :key="g.group"
            :index="g.group"
          >
            <template #title>
              <el-icon><component :is="g.icon" /></el-icon>
              <span>{{ g.group }}</span>
            </template>
            <el-menu-item
              v-for="it in g.items.filter((i) => canSee(i))"
              :key="it.path"
              :index="it.path"
            >
              {{ it.title }}
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <!-- 顶栏 -->
      <el-header class="header">
        <el-icon class="collapse-btn" @click="app.toggleSidebar">
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
        <div class="crumb">{{ currentTitle }}</div>

        <!-- 多租户 UI：当前租户徽章（数据按 JWT 租户行级隔离，BFF 强制） -->
        <div class="tenant-badge" v-if="tenantCode">
          <el-tag type="primary" size="small" effect="dark">
            租户: {{ tenantCode }}
          </el-tag>
          <span class="text-muted tenant-label">{{ displayName }}</span>
        </div>

        <div class="flex-1"></div>
        <el-dropdown @command="onCommand">
          <span class="user-menu">
            <el-avatar :size="28" class="avatar">{{ initial }}</el-avatar>
            <span class="username">{{ displayName }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="refresh" :disabled="refreshing">
                <el-icon><Refresh /></el-icon> 刷新权限
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon> 退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { menu } from '@/config/menu'

const route = useRoute()
const auth = useAuthStore()
const app = useAppStore()

const collapsed = computed(() => app.sidebarCollapsed)
const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta.title || '')

// 多租户 UI：当前租户 / 用户显示名（来自 JWT claims / 登录）
const tenantCode = computed(() => auth.user?.tenant_code || auth.tenantCode)
const displayName = computed(
  () => auth.user?.display_name || auth.user?.username || '用户'
)
const initial = computed(() => (displayName.value || '?').slice(0, 1).toUpperCase())

// 菜单可见性：按当前用户 scope 过滤（agent:use:* 通配 → 视为有 agent 访问权）
function canSee(item) {
  if (!item.scope) return true
  if (item.scope === 'agent:use:*') return true
  return auth.hasScope(item.scope)
}
const visibleGroups = computed(() => {
  const groups = menu
    .map((g) => ({ ...g, items: g.items.filter((i) => canSee(i)) }))
    .filter((g) => g.items.length > 0)
  // 空 group 隐藏
  return groups
})

const refreshing = ref(false)
async function refreshScopes() {
  // 无感续期 access（顺带从新 token 重读 scopes）
  refreshing.value = true
  try {
    await auth.refreshAccessToken()
    auth.hydrateFromToken()
    ElMessage.success('权限已刷新')
  } catch (e) {
    ElMessage.error('刷新失败，请重新登录')
  } finally {
    refreshing.value = false
  }
}

async function onCommand(cmd) {
  if (cmd === 'refresh') return refreshScopes()
  if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
    } catch {
      return
    }
    await auth.logout()
    ElMessage.success('已退出')
    location.href = '/login'
  }
}

onMounted(() => {
  // 进入系统后水合一次 scopes（若登录时未带全）
  if (auth.isLoggedIn) auth.hydrateFromToken()
})
</script>

<style scoped>
.layout { height: 100vh; }
.aside {
  background: var(--jj-sidebar-bg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.logo-icon {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
}
.logo-text { font-size: 16px; font-weight: 600; }
.menu-scroll { flex: 1; }
.el-menu { border-right: none; }
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  height: 56px;
}
.collapse-btn { font-size: 20px; cursor: pointer; color: #606266; }
.crumb { font-size: 16px; font-weight: 600; }
.tenant-badge { display: flex; align-items: center; gap: 8px; }
.tenant-label { font-size: 13px; }
.user-menu {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #303133;
}
.username { font-size: 14px; }
.avatar { background: #409eff; color: #fff; font-weight: 600; }
.main { padding: 0; overflow: auto; }
</style>
