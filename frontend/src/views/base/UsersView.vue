<template>
  <div class="page">
    <h2>用户管理 <span class="text-muted">（BASE-01，scope iam:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon> 新建用户
      </el-button>
      <el-input v-model="kw" placeholder="按用户名/邮箱过滤" clearable style="width:220px" @input="debouncedLoad" />
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="username" label="用户名" width="160" />
      <el-table-column prop="display_name" label="显示名" width="140" />
      <el-table-column prop="email" label="邮箱" min-width="180" />
      <el-table-column label="角色" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles || row.role_names || []" :key="r" size="small" style="margin:2px">
            {{ r }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="onResetPw(row)">重置密码</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="toolbar" style="margin-top:12px">
      <el-pagination
        v-model:current-page="page"
        :total="total"
        :page-size="pageSize"
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </div>

    <!-- 创建/编辑 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑用户' : '新建用户'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名" v-if="!editing">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码" v-if="!editing">
          <el-input v-model="form.password" type="password" show-password placeholder="≥6 位" />
        </el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="状态" v-if="editing">
          <el-select v-model="form.status">
            <el-option label="启用" value="active" />
            <el-option label="禁用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_names" multiple filterable placeholder="选择角色">
            <el-option v-for="r in roles" :key="r.name" :label="r.name" :value="r.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwDialog" title="重置密码" width="380px">
      <el-form label-width="80px">
        <el-form-item label="新密码">
          <el-input v-model="newPw" type="password" show-password placeholder="≥6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwDialog=false">取消</el-button>
        <el-button type="primary" @click="onResetPwConfirm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/iam'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const kw = ref('')
const dialog = ref(false)
const editing = ref(null)
const form = ref({ username: '', password: '', display_name: '', email: '', status: 'active', role_names: [] })
const roles = ref([])
const pwDialog = ref(false)
const pwTarget = ref(null)
const newPw = ref('')

let timer
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value = 1; load() }, 300)
}

async function load() {
  loading.value = true
  try {
    const res = await api.listUsers({ page: page.value, page_size: pageSize.value })
    let items = res.data?.items || []
    if (kw.value) {
      const q = kw.value.toLowerCase()
      items = items.filter((r) => (r.username || '').toLowerCase().includes(q) || (r.email || '').toLowerCase().includes(q))
    }
    rows.value = items
    total.value = res.data?.total ?? items.length
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  const res = await api.listRoles()
  roles.value = res.data?.items || res.data || []
}

function openCreate() {
  editing.value = null
  form.value = { username: '', password: '', display_name: '', email: '', status: 'active', role_names: [] }
  dialog.value = true
}
function openEdit(row) {
  editing.value = row
  form.value = {
    username: row.username,
    display_name: row.display_name || '',
    email: row.email || '',
    status: row.status || 'active',
    role_names: (row.roles || row.role_names || []).map((r) => (typeof r === 'string' ? r : r.name)),
  }
  dialog.value = true
}

async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      const body = {}
      if (form.value.display_name !== undefined) body.display_name = form.value.display_name
      if (form.value.email !== undefined) body.email = form.value.email
      body.status = form.value.status
      body.role_names = form.value.role_names
      await api.updateUser(editing.value.id, body)
      ElMessage.success('已更新')
    } else {
      if (form.value.password.length < 6) return ElMessage.warning('密码至少 6 位')
      await api.createUser(form.value)
      ElMessage.success('已创建')
    }
    dialog.value = false
    load()
  } catch (e) { /* http 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除用户 ${row.username}？（软删除）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteUser(row.id)
  ElMessage.success('已删除')
  load()
}
function onResetPw(row) {
  pwTarget.value = row
  newPw.value = ''
  pwDialog.value = true
}
async function onResetPwConfirm() {
  if (newPw.value.length < 6) return ElMessage.warning('密码至少 6 位')
  await api.resetPassword(pwTarget.value.id, { password: newPw.value })
  ElMessage.success('已重置')
  pwDialog.value = false
}

onMounted(() => { load(); loadRoles() })
</script>
