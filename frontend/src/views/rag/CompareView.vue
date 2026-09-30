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
      <!-- 左栏：原文档（txt/md 直读高亮；pdf iframe；png/jpg img；docx docx-preview 渲染；xlsx SheetJS 表格） -->
      <div class="pane left" ref="leftScroll">
        <div class="pane-head">
          <span>原文档</span>
          <el-tag size="small" :type="leftTagType">{{ leftTagText }}</el-tag>
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
          <div v-else-if="doc && doc.doc_type === 'docx'" class="orig-docx" ref="docxRef"></div>
          <div v-else-if="doc && doc.doc_type === 'xlsx'" class="orig-xlsx" ref="xlsxRef">
            <div v-if="!xlsxSheets.length" class="text-muted">xlsx 无有效工作表</div>
            <el-tabs v-else v-model="xlsxActive" type="card">
              <el-tab-pane v-for="s in xlsxSheets" :key="s.name" :label="s.name" :name="s.name">
                <table class="xlsx-table">
                  <tbody>
                    <tr v-for="(row, ri) in s.rows" :key="ri">
                      <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>
              </el-tab-pane>
            </el-tabs>
          </div>
          <div v-else class="text-muted">
            原文档为 {{ doc?.doc_type || '-' }} 类型，当前降级渲染（{{ leftTagText }}）。
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
          <div v-for="c in chunks" :key="c.id" :data-cid="c.id"
            class="chunk-item" :class="{ active: selectedChunk?.id === c.id, is_table: c.is_table }"
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
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { renderAsync } from 'docx-preview'
import * as XLSX from 'xlsx'
import * as api from '@/api/rag'
import { strategyLabel, describePos } from '@/utils/rag'
import { highlightQuery, clearMarks } from '@/utils/highlight'
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
const leftTagType = ref('info')
const leftTagText = ref('')
const origText = ref(null)
const docxRef = ref(null)
const xlsxRef = ref(null)
const xlsxSheets = ref([])
const xlsxActive = ref('')
const leftScroll = ref(null)
const chunkList = ref(null)

// 编辑
const editDialog = ref(false)
const editTarget = ref(null)
const editContent = ref('')
const saving = ref(false)

// 当前高亮的字符区间 [start, end)（仅文本类 txt/md）
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

function setLeftTag(type, text) {
  leftTagType.value = type
  leftTagText.value = text
}

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

// docx → docx-preview 渲染为 HTML（bodyContainer 传入）
async function renderDocx(buf) {
  const container = docxRef.value
  if (!container) return
  container.innerHTML = ''
  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })
  try {
    await renderAsync(blob, container)
  } catch (e) {
    container.innerHTML = `<div class="text-muted">docx 渲染失败：${e && e.message ? e.message : e}</div>`
  }
}

// xlsx → SheetJS 解析为多 sheet 表格（首个 sheet 默认，多 sheet 给 tab 切换）
function renderXlsx(buf) {
  xlsxSheets.value = []
  xlsxActive.value = ''
  let wb
  try {
    wb = XLSX.read(new Uint8Array(buf), { type: 'array' })
  } catch (e) {
    xlsxSheets.value = [{ name: 'error', rows: [['xlsx 解析失败：' + (e && e.message ? e.message : e)]] }]
    xlsxActive.value = 'error'
    return
  }
  const sheets = []
  for (const name of wb.SheetNames) {
    const ws = wb.Sheets[name]
    if (!ws) continue
    const rows = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' })
      .map((r) => (Array.isArray(r) ? r.map((c) => (c == null ? '' : String(c))) : [String(r)]))
    sheets.push({ name, rows })
  }
  xlsxSheets.value = sheets
  xlsxActive.value = sheets[0]?.name || ''
}

async function loadOriginal() {
  // 左栏渲染源：GET /api/rag/kbs/{id}/docs/{docId}/file
  const url = api.getDocFileUrl(kbId, docId)
  const token = auth.accessToken
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) {
    setLeftTag('info', '原文获取失败')
    return
  }
  const ct = res.headers.get('content-type') || ''
  const type = doc.value?.doc_type
  if (type === 'txt' || type === 'md' || ct.includes('text')) {
    // 文本类直读高亮
    leftText.value = await res.text()
    setLeftTag('success', '可高亮')
  } else if (type === 'png' || type === 'jpg') {
    fileUrl.value = URL.createObjectURL(await res.blob())
    setLeftTag('info', '图片直显（整图=1 chunk）')
  } else if (type === 'pdf') {
    fileUrl.value = URL.createObjectURL(await res.blob())
    setLeftTag('info', 'PDF 预览')
  } else if (type === 'docx') {
    await renderDocx(await res.arrayBuffer())
    setLeftTag('success', '已渲染')
  } else if (type === 'xlsx') {
    renderXlsx(await res.arrayBuffer())
    setLeftTag('success', '已渲染')
  } else {
    setLeftTag('info', `${type} 降级渲染`)
  }
}

function reloadAll() {
  hlRange.value = null
  selectedChunk.value = null
  loadDoc().then(() => { loadChunks(); loadOriginal() })
}

// 右→左联动：点 chunk → 高亮原文 + 滚动
async function onChunkClick(c) {
  selectedChunk.value = c
  hlRange.value = null
  const type = doc.value?.doc_type
  if (type === 'txt' || type === 'md') {
    // 文本类：取 chunk 原文字符区间精确高亮
    try {
      const res = await api.getChunkLocation(kbId, docId, c.id)
      const pos = res.data?.pos
      if (pos && typeof pos === 'object' && pos.char_start != null) {
        hlRange.value = [pos.char_start, pos.char_end]
        await nextTick()
        scrollToOffset(pos.char_start)
      }
    } catch (e) { /* 忽略定位失败 */ }
    return
  }
  if (type === 'docx' || type === 'xlsx') {
    // docx/xlsx：在渲染后 DOM 中按 chunk 文本匹配高亮（最佳努力；匹配不到仅显示原文不报错）
    await nextTick()
    const root = type === 'docx' ? docxRef.value : xlsxRef.value
    if (root) {
      clearMarks(root)
      highlightQuery(root, c.content)
      const mk = root.querySelector('mark.hl')
      if (mk) mk.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    return
  }
  // pdf/图片：不高亮（设计降级）
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
    const hit = chunks.value.find((c) => c.id === primary)
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
  const el = container?.querySelector(`[data-cid="${c.id}"]`) ||
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
    await api.updateChunk(kbId, docId, editTarget.value.id, { content: editContent.value })
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
.orig-docx :deep(mark.hl) { background: #fff3b0; outline: 1px solid #e6a23c; cursor: pointer; }
.orig-xlsx :deep(mark.hl) { background: #fff3b0; outline: 1px solid #e6a23c; cursor: pointer; }
.orig-img { max-width: 100%; height: auto; }
.orig-pdf { width: 100%; height: 100%; border: none; }
/* docx-preview 渲染容器 */
.orig-docx { min-height: 60px; }
.orig-docx :deep(.docx-wrapper) { max-width: 100%; }
.orig-docx :deep(.docx) { font-size: 14px; line-height: 1.6; }
/* xlsx 表格 */
.orig-xlsx :deep(table.xlsx-table) { border-collapse: collapse; width: 100%; font-size: 13px; }
.orig-xlsx :deep(table.xlsx-table td) {
  border: 1px solid #ebeef5; padding: 4px 8px; white-space: pre-wrap; word-break: break-word;
}
.orig-xlsx :deep(table.xlsx-table tr:first-child td) { background: #f5f7fa; font-weight: 600; }
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
