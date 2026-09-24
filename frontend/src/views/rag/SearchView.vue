<template>
  <div class="page">
    <h2>检索测试 <span class="text-muted">（RAG-06..09，scope rag:search）</span></h2>
    <el-card class="search-card">
      <el-form label-width="110px">
        <el-form-item label="知识库">
          <el-select v-model="kbIds" multiple filterable placeholder="选择 1~N 个知识库（同租户）" style="width:100%">
            <el-option v-for="k in kbs" :key="k.id" :label="`${k.name} (${k.embedding_dim}d)`" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="查询">
          <el-input v-model="query" placeholder="输入检索问题" @keyup.enter="onSearch" />
        </el-form-item>
        <el-form-item label="top_k">
          <el-input-number v-model="topK" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="阈值">
          <el-input-number v-model="threshold" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="使用 rerank">
          <el-switch v-model="useRerank" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="searching" @click="onSearch"><el-icon><Search /></el-icon> 检索</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="results" class="result-card">
      <template #header>
        <span>结果：{{ results.items.length }} 条</span>
        <el-tag size="small" style="margin-left:8px" :type="results.reranked ? 'success' : 'info'">
          {{ results.reranked ? '已 rerank' : '纯向量' }}
        </el-tag>
        <span class="text-muted" style="margin-left:8px">top_k={{ results.top_k }} 阈值={{ results.threshold }}</span>
      </template>
      <div v-for="(r, i) in results.items" :key="r.chunk_id" class="result-item">
        <div class="result-head">
          <el-tag size="small" type="primary">#{{ i + 1 }}</el-tag>
          <el-tag size="small" :type="r.is_official ? 'warning' : 'info'" style="margin-left:6px">
            {{ r.is_official ? '官方' : '普通' }}
          </el-tag>
          <span class="mono text-muted" style="margin-left:8px">{{ r.doc_file_name || '-' }}</span>
          <el-tag size="small" type="info" style="margin-left:8px" v-if="r.pos">{{ describePos(r.pos) }}</el-tag>
          <span class="flex-1"></span>
          <b class="score">score {{ (r.score * 100).toFixed(1) }}%</b>
        </div>
        <div class="result-content">{{ r.content }}</div>
        <div v-if="r.parent_content" class="result-parent text-muted">父: {{ r.parent_content.slice(0, 120) }}…</div>
      </div>
      <div v-if="!results.items.length" class="text-muted">无命中</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/rag'
import { describePos } from '@/utils/rag'

const kbs = ref([])
const kbIds = ref([])
const query = ref('')
const topK = ref(5)
const threshold = ref(0.3)
const useRerank = ref(true)
const searching = ref(false)
const results = ref(null)

async function loadKbs() {
  const res = await api.listKbs({ page: 1, page_size: 200, status: 'active' })
  kbs.value = res.data?.items || []
}
async function onSearch() {
  if (!kbIds.value.length) return ElMessage.warning('选择知识库')
  if (!query.value.trim()) return ElMessage.warning('输入查询')
  searching.value = true
  try {
    const res = await api.ragSearch({
      kb_ids: kbIds.value,
      query: query.value,
      top_k: topK.value,
      score_threshold: threshold.value,
      use_rerank: useRerank.value,
    })
    results.value = res.data
  } catch (e) {} finally { searching.value = false }
}
onMounted(loadKbs)
</script>

<style scoped>
.search-card { margin-bottom: 12px; }
.result-item { border-bottom: 1px solid #ebeef5; padding: 10px 0; }
.result-head { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.score { color: #409eff; }
.result-content { font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.result-parent { margin-top: 6px; font-size: 12px; }
</style>
