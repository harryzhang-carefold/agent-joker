<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="brand">
        <h1>agent-joker</h1>
        <p class="sub">WebConsole 管理台</p>
      </div>
      <el-form :model="form" @submit.prevent="onLogin" label-position="top">
        <el-form-item label="租户编码">
          <el-input v-model="form.tenant_code" placeholder="如 acme" clearable />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="admin" clearable @keyup.enter="onLogin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="••••••" show-password @keyup.enter="onLogin" />
        </el-form-item>
        <el-button type="primary" class="full" :loading="loading" @click="onLogin">登录</el-button>
      </el-form>
      <div class="hint text-muted">
        种子租户 <code>acme</code> / 用户 <code>admin</code>（密码见 .env SEED_ADMIN_PASSWORD）<br />
        平台管理员（租户管理）：租户 <code>system</code> / 用户
        <code>platform</code>（SEED_PLATFORM_ADMIN_USERNAME）
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

// 解码 JWT（access）claims：tenant_id / user_id / scopes（本地解，仅用于 UI 展示与权限判断；
// 权威身份仍以 BFF 校验为准，前端解码只作展示辅助）。
function decodeJwt(accessToken) {
  try {
    const payload = accessToken.split('.')[1]
    const b64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const pad = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const json = decodeURIComponent(
      atob(pad)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
    return JSON.parse(json)
  } catch {
    return {}
  }
}

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ tenant_code: 'acme', username: 'admin', password: '' })

async function onLogin() {
  if (!form.tenant_code || !form.username || !form.password) {
    ElMessage.warning('请填写租户编码 / 用户名 / 密码')
    return
  }
  loading.value = true
  try {
    const res = await login({
      tenant_code: form.tenant_code,
      username: form.username,
      password: form.password,
    })
    const d = res.data
    const claims = decodeJwt(d.access_token)
    auth.setTokens({
      access_token: d.access_token,
      refresh_token: d.refresh_token,
      user: {
        tenant_code: form.tenant_code,
        tenant_id: claims.tenant_id || null,
        user_id: claims.user_id || null,
        username: form.username,
        display_name: form.username,
        scopes: claims.scopes || [],
      },
    })
    ElMessage.success('登录成功')
    const redirect = route.query.redirect || '/'
    router.replace(redirect)
  } catch (e) {
    const detail = e?.response?.data?.detail || '登录失败'
    ElMessage.error(typeof detail === 'string' ? detail : '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2937 0%, #0f172a 100%);
}
.login-card { width: 360px; }
.brand { text-align: center; margin-bottom: 18px; }
.brand h1 { font-size: 26px; margin: 0; color: #409eff; }
.brand .sub { color: #909399; margin: 6px 0 0; font-size: 13px; }
.hint { margin-top: 14px; text-align: center; }
</style>
