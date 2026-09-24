<template>
  <div class="page compare-page">
    <div class="toolbar" style="margin-bottom:8px">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> 返回文档列表</el-button>
      <span v-if="doc" class="flex-1">
        <b>{{ doc.file_name }}</b>
        <el-tag size="small" style="margin-left:8px">{{ doc.doc_type }}</el-tag>
        <el-tag :type="doc.status === 'ready' ? 'success' : 'warning'" size="small" style="margin-left:8px">{{ doc.status }}</el-tag>
        <el-tag size="small" style="margin-left:8px">{{ strategyLabel(doc.split_strategy) }}</el-tag>
      </span>
      <el-button size="small" @click="reloadAll"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <div class="split">
      <!-- 左栏：原文档（txt/文本直读高亮；图片/PDF/docx 按类型降级） -->
      <div class="pane left" ref="leftScroll">
        <div class="pane-head">
          <span>原文档</span>
          <el-tag size="small" :type="leftRendered ? 'success' : 'info'">
            {{ leftRendered ? '可高亮' : leftHint }}
          </el-tag>
        </div>
        <div class="pane-body">
          <img v-if="doc && (doc.doc_type === 'png' || doc.doc_type === 'jpg') && fileUrl"
            :src="fileUrl" class="orig-img" />
          <iframe v-else-if="doc && doc.doc_type === 'pdf' && fileUrl" :src="fileUrl" class="orig-pdf"></iframe>
          <div v-else-if="leftText" class="orig-text" ref="origText">
            <!-- 高亮：按字符偏移切分，命中段用 <mark> 包裹 -->
            <template v-for="(seg, i) in leftSegments" :key="i">
              <mark v-if="seg.hl" class="hl" :data-start="seg.start" :data-end="seg.end" @click="onLeftClickSeg(i, seg)">{{ seg.text }}</mark>
              <span v-else :data-start="seg.start" :data-end="seg.end">{{ seg.text }}</span>
            </template>
          </div>
          <div v-else class="text-muted">
            原文档为 {{ doc?.doc_type || '-' }} 类型，当前降级渲染（{{ leftHint }}）。
            点右栏 chunk 仍可高亮原文（文本类）/查看 chunk 详情。
          </div>
        </div>
      </div>

      <!-- 右栏：chunk 切片列表 -->
      <div class="pane right">
        <div class="pane-head">
          <span>chunk 切片（{{ chunks.length }}）</span>
          <el-tag size="small" v-if="selectedChunk">已选 #{{ selectedChunk.chunk_index }}</el-tag>
        </div>
        <div class="pane-body chunk-list" ref="chunkList">
          <div v-if="chunksLoading" class="text-muted">加载中…</div>
          <div v-for="c in chunks" :key="c.chunk_id" :data-cid="c.chunk_id"
            class="chunk-item" :class="{ active: selectedChunk?.chunk_id === c.chunk_id, is_table: c.is_table }"
            @click="onChunkClick(c)">
            <div class="chunk-head">
              <el-tag size="small" type="primary">#{{ c.chunk_index }}</el-tag>
              <el-tag v-if="c.is_table" size="small" type="warning" style="margin-left:6px">表格</el-tag>
              <el-tag v-if="c.parent_id" size="small" type="info" style="margin-left:6px">子</el-tag>
              <el-tag v-if="c.edited_at" size="small" type="danger" style="margin-left:6px">已编辑</el-tag>
              <span class="text-muted" style="margin-left:6px">{{ describePos(c.pos, doc?.doc_type) }}</span>
            </div>
            <div class="chunk-content">{{ c.content }}</div>
            <div class="chunk-actions">
              <el-button size="small" text @click.stop="openEdit(c)">编辑</el-button>
            </div>
          </div>
          <div v-if="!chunks.length && !chunksLoading" class="text-muted">暂无 chunk</div>
        </div>
      </div>
    </div>

    <!-- 编辑 chunk（RAG-05 验收 2/4） -->
    <el-dialog v-model="editDialog" :title="`编辑 chunk #${editTarget?.chunk_index}`" width="640px">
      <p class="text-muted">修改后重新计算向量写入本库向量表（D-C），edited_at 留痕；右栏刷新，左栏原文不可变。</p>
      <el-input v-model="editContent" type="textarea" :rows="10" />
      <template #footer>
        <el-button @click="editDialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onEditConfirm">保存并重嵌入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as api from '@/api/rag'
import { strategyLabel, describePos } from '@/utils/rag'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const kbId = route.params.kbId
const docId = route.params.docId

const doc = ref(null)
const chunks = ref([])
const chunksLoading = ref(false)
const selectedChunk = ref(null)
const fileUrl = ref('')
const leftText = ref('')
const leftRendered = ref(false)
const leftHint = ref('')
const origText = ref(null)
const leftScroll = ref(null)
const chunkList = ref(null)

// 编辑
const editDialog = ref(false)
const editTarget = ref(null)
const editContent = ref('')
const saving = ref(false)

// 当前高亮的字符区间 [start, end)
const hlRange = ref(null)
const leftSegments = computed(() => {
  if (!leftText.value) return []
  const t = leftText.value
  if (!hlRange.value) return [{ text: t, hl: false, start: 0, end: t.length }]
  const [s, e] = hlRange.value
  const segs = []
  if (s > 0) segs.push({ text: t.slice(0, s), hl: false, start: 0, end: s })
  segs.push({ text: t.slice(s, e), hl: true, start: s, end: e })
  if (e < t.length) segs.push({ text: t.slice(e), hl: false, start: e, end: t.length })
  return segs
})

function back() { router.push(`/rag/kbs/${kbId}`) }

async function loadDoc() {
  const res = await api.getDoc(kbId, docId)
  doc.value = res.data
}

async function loadChunks() {
  chunksLoading.value = true
  try {
    const res = await api.listChunks(kbId, docId, { page: 1, page_size: 500 })
    chunks.value = res.data?.items || []
  } finally { chunksLoading.value = false }
}

async function loadOriginal() {
  // 左栏渲染源：GET /api/rag/kbs/{id}/docs/{docId}/file
  const url = api.getDocFileUrl(kbId, docId)
  const res = await fetch(url, { headers: { Authorization: `Bearer ${auth.accessToken}` } })
  if (!res.ok) return
  const ct = res.headers.get('content-type') || ''
  const type = doc.value?.doc_type
  // 文本类直读高亮
  if (type === 'txt' || type === 'md' || ct.includes('text')) {
    leftText.value = await res.text()
    leftRendered.value = true
    leftHint.value = ''
  } else if (type === 'png' || type === 'jpg' || type === 'pdf') {
    fileUrl.value = URL.createObjectURL(await res.blob())
    leftRendered.value = false
    leftHint.value = type === 'pdf' ? 'PDF 预览' : '图片直显（整图=1 chunk）'
  } else {
    // docx/xlsx 降级：不渲染高亮，仅提示
    leftRendered.value = false
    leftHint.value = `${type} 降级渲染`
  }
}

function reloadAll() {
  loadDoc().then(() => { loadChunks(); loadOriginal() })
}

// 右→左联动：点 chunk → 取 location → 高亮原文 + 滚动
async function onChunkClick(c) {
  selectedChunk.value = c
  hlRange.value = null
  // 右→左：取 chunk 原文位置
  try {
    const res = await api.getChunkLocation(kbId, docId, c.chunk_id)
    const pos = res.data?.pos
    if (pos && leftRendered.value && typeof pos === 'object' && pos.char_start != null) {
      hlRange.value = [pos.char_start, pos.char_end]
      await nextTick()
      scrollToOffset(pos.char_start)
    }
  } catch (e) { /* 忽略定位失败 */ }
}

// 左→右联动：点原文某段 → by-location 反查该区间包含的 chunk → 右栏定位
async function onLeftClickSeg(i, seg) {
  if (!seg) return
  const start = seg.start
  const end = seg.end
  if (start === end) return
  const pos = { char_start: start, char_end: end }
  try {
    const res = await api.getChunksByLocation(kbId, docId, pos)
    const primary = res.data?.primary_chunk_id
    const hit = chunks.value.find((c) => c.chunk_id === primary)
    if (hit) {
      selectedChunk.value = hit
      hlRange.value = [start, end]
      scrollChunkTo(hit)
      ElMessage.info(`定位到 chunk #${hit.chunk_index}${res.data?.items?.length > 1 ? `（共 ${res.data.items.length} 命中）` : ''}`)
    } else {
      ElMessage.info('该位置无命中 chunk')
    }
  } catch (e) { /* 忽略 */ }
}

function scrollToOffset(offset) {
  // 找到包含 offset 的段，滚动到其位置
  const seg = leftSegments.value.find((s) => offset >= s.start && offset < s.end) || leftSegments.value[0]
  if (!seg) return
  const container = leftScroll.value
  const el = container?.querySelector(`[data-start="${seg.start}"]`)
  if (el && container) {
    const elTop = el.getBoundingClientRect().top - container.getBoundingClientRect().top
    container.scrollTo({ top: Math.max(0, elTop - 80), behavior: 'smooth' })
  }
}

function scrollChunkTo(c) {
  const container = chunkList.value
  const el = container?.querySelector(`[data-cid="${c.chunk_id}"]`) ||
    Array.from(container?.children || []).find((n) => n.textContent?.includes(`#${c.chunk_index}`))
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function openEdit(c) {
  editTarget.value = c
  editContent.value = c.content
  editDialog.value = true
}
async function onEditConfirm() {
  if (!editContent.value.trim()) return ElMessage.warning('内容不能为空')
  saving.value = true
  try {
    await api.updateChunk(kbId, docId, editTarget.value.chunk_id, { content: editContent.value })
    ElMessage.success('已编辑并重嵌入向量')
    editDialog.value = false
    loadChunks()
  } catch (e) {} finally { saving.value = false }
}

onMounted(async () => {
  await loadDoc()
  await loadChunks()
  await loadOriginal()
})
</script>

<style scoped>
.compare-page { display: flex; flex-direction: column; }
.split { display: flex; gap: 12px; flex: 1; min-height: 0; }
.pane {
  display: flex; flex-direction: column; min-height: 0;
  border: 1px solid #e4e7ed; border-radius: 6px; background: #fff; overflow: hidden;
}
.pane.left, .pane.right { flex: 1; }
.pane-head {
  padding: 8px 12px; border-bottom: 1px solid #ebeef5;
  display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px;
}
.pane-body { flex: 1; overflow: auto; padding: 10px 12px; }
.orig-text { font-size: 14px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.orig-text .hl { background: #fff3b0; outline: 1px solid #e6a23c; cursor: pointer; }
.orig-img { max-width: 100%; height: auto; }
.orig-pdf { width: 100%; height: 100%; border: none; }
.chunk-list { display: flex; flex-direction: column; gap: 8px; }
.chunk-item {
  border: 1px solid #e4e7ed; border-radius: 6px; padding: 8px;
  cursor: pointer; transition: all .15s;
}
.chunk-item:hover { border-color: #409eff; }
.chunk-item.active { border-color: #409eff; background: #ecf5ff; box-shadow: 0 0 0 1px #409eff inset; }
.chunk-item.is_table { border-left: 3px solid #e6a23c; }
.chunk-head { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.chunk-content { font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 140px; overflow: auto; }
.chunk-actions { margin-top: 4px; }
</style>
