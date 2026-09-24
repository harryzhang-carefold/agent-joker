import http from './http'

// llm（LLM-01/02/03）：endpoint / embedding / reranker
const base = (kind) => `/api/llm/${kind}`

export const listEndpoints = (params) => http.get(base('endpoints'), { params })
export const getEndpoint = (id) => http.get(`${base('endpoints')}/${id}`)
export const createEndpoint = (body) => http.post(base('endpoints'), body)
export const updateEndpoint = (id, body) => http.put(`${base('endpoints')}/${id}`, body)
export const deleteEndpoint = (id) => http.delete(`${base('endpoints')}/${id}`)
export const testEndpoint = (id) => http.post(`${base('endpoints')}/${id}/test`)

export const listEmbeddings = (params) => http.get(base('embeddings'), { params })
export const getEmbedding = (id) => http.get(`${base('embeddings')}/${id}`)
export const createEmbedding = (body) => http.post(base('embeddings'), body)
export const updateEmbedding = (id, body) => http.put(`${base('embeddings')}/${id}`, body)
export const deleteEmbedding = (id) => http.delete(`${base('embeddings')}/${id}`)
export const testEmbedding = (id) => http.post(`${base('embeddings')}/${id}/test`)

export const listRerankers = (params) => http.get(base('rerankers'), { params })
export const getReranker = (id) => http.get(`${base('rerankers')}/${id}`)
export const createReranker = (body) => http.post(base('rerankers'), body)
export const updateReranker = (id, body) => http.put(`${base('rerankers')}/${id}`, body)
export const deleteReranker = (id) => http.delete(`${base('rerankers')}/${id}`)
export const testReranker = (id) => http.post(`${base('rerankers')}/${id}/test`)
