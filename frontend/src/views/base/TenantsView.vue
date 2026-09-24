<template>
  <div class="page">
    <!-- S17/BUG-07：非平台管理员直接改 URL 进入 → 403 兜底 + 友好提示（菜单已按权限隐藏） -->
    <el-alert v-if="forbidden" type="warning" :closable="false" show-icon style="margin-bottom:16px">
      <template #title>
        无权限访问租户管理
      </template>
      <div>{{ forbiddenHint }}</div>
    </el-alert>
    <h2 v-else>租户管理 <span class="text-muted">（多租户，平台管理视角，scope iam:manage）</span></h2>
    <div class="toolbar" v-if="!forbidden">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建租户</el-button>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>
    <el-alert v-if="!forbidden" type="info" :closable="false" style="margin-bottom:12px"
      title="隔离视图：当前登录用户只能管理其所属租户的数据；此处列表为平台管理视角（可见全部租户）。普通租户用户的数据行级过滤由 BFF 强制。" />
    <el-table :data="rows" v-if="!forbidden" v-loading="loading" stripe border>
      <el-table-column prop="code" label="编码" width="160" />
      <el-table-column prop="name" label="名称" min-width="200" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="200" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑租户' : '新建租户'" width="460px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="编码" v-if="!editing">
          <el-input v-model="form.code" placeholder="全局唯一，如 acme" />
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="状态" v-if="editing">
          <el-select v-model="form.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/iam'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const dialog = ref(false)
const editing = ref(null)
const form = ref({ code: '', name: '', status: 'active' })
// S17/BUG-07：非平台管理员直接改 URL 进入 → 403 兜底 + 友好提示
const forbidden = ref(false)
const forbiddenHint = ref('')

async function load() {
  loading.value = true
  try {
    const res = await api.listTenants({ page: 1, page_size: 200 }, { silent: true })
    rows.value = res.data?.items || []
    forbidden.value = false
  } catch (e) {
    const status = e?.response?.status
    if (status === 403) {
      forbidden.value = true
      forbiddenHint.value =
        e?.response?.data?.detail ||
        '需要平台管理员权限，请用 system 租户的平台管理员登录'
    }
  } finally { loading.value = false }
}
function openCreate() {
  editing.value = null
  form.value = { code: '', name: '', status: 'active' }
  dialog.value = true
}
function openEdit(row) {
  editing.value = row
  form.value = { code: row.code, name: row.name, status: row.status || 'active' }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      await api.updateTenant(editing.value.id, { name: form.value.name, status: form.value.status })
    } else {
      await api.createTenant(form.value)
    }
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
onMounted(load)
</script>
