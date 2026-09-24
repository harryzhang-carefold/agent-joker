import http from './http'

// storage（STORE-03/05）
export const storageHealthz = () => http.get('/api/storage/healthz')
export const listBackends = () => http.get('/api/storage/backends')
export const listFiles = (params) => http.get('/api/storage/files', { params })
export const uploadFile = (file, source = 'api') => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post(`/api/storage/files?source=${source}`, fd)
}
export const deleteFile = (fileName) =>
  http.delete(`/api/storage/files/${encodeURIComponent(fileName)}`)
export const listUploadRecords = (params) =>
  http.get('/api/storage/upload-records', { params })
