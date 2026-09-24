import http from './http'

// rag（RAG-01..09/11）：知识库 / 文档 / chunk / 检索 / 切分对比
const kb = (id) => `/api/rag/kbs/${id}`

export const listKbs = (params) => http.get('/api/rag/kbs', { params })
export const getKb = (id) => http.get(kb(id))
export const createKb = (body) => http.post('/api/rag/kbs', body)
export const updateKb = (id, body) => http.put(kb(id), body)
export const deleteKb = (id) => http.delete(kb(id))
export const reindexKb = (id, body) => http.post(`${kb(id)}/reindex`, body)

// 文档
export const uploadDoc = (id, file, { tag, split_strategy, split_params } = {}) => {
  const fd = new FormData()
  fd.append('file', file)
  const qs = new URLSearchParams()
  if (tag) qs.set('tag', tag)
  if (split_strategy) qs.set('split_strategy', split_strategy)
  if (split_params) qs.set('split_params', JSON.stringify(split_params))
  const q = qs.toString()
  return http.post(`${kb(id)}/docs${q ? '?' + q : ''}`, fd)
}
export const listDocs = (id, params) => http.get(`${kb(id)}/docs`, { params })
export const getDoc = (id, docId) => http.get(`${kb(id)}/docs/${docId}`)
export const updateDoc = (id, docId, body) => http.put(`${kb(id)}/docs/${docId}`, body)
export const deleteDoc = (id, docId) => http.delete(`${kb(id)}/docs/${docId}`)
export const retryDoc = (id, docId) => http.post(`${kb(id)}/docs/${docId}/retry`)
export const resplitDoc = (id, docId, body) => http.post(`${kb(id)}/docs/${docId}/resplit`, body)
// 原文档二进制（左栏渲染源）
export const getDocFileUrl = (id, docId) =>
  `/api/rag/kbs/${id}/docs/${docId}/file`

// chunk（RAG-05/11 双向联动）
export const listChunks = (id, docId, params) =>
  http.get(`${kb(id)}/docs/${docId}/chunks`, { params })
export const getChunkLocation = (id, docId, chunkId) =>
  http.get(`${kb(id)}/docs/${docId}/chunks/${chunkId}/location`)
export const getChunksByLocation = (id, docId, pos) =>
  http.get(`${kb(id)}/docs/${docId}/chunks/by-location`, {
    params: { pos: typeof pos === 'string' ? pos : JSON.stringify(pos) },
  })
export const updateChunk = (id, docId, chunkId, body) =>
  http.put(`${kb(id)}/docs/${docId}/chunks/${chunkId}`, body)

// 检索（RAG-06..09，scope rag:search）
export const ragSearch = (body) => http.post('/api/rag/search', body)
