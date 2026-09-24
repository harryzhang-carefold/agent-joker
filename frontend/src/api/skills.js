import http from './http'

// skills（SKILL-01/02）
export const listSkills = (params) => http.get('/api/skills', { params })
export const getSkill = (id) => http.get(`/api/skills/${id}`)
export const createSkill = (body) => http.post('/api/skills', body)
export const updateSkill = (id, body) => http.put(`/api/skills/${id}`, body)
export const deleteSkill = (id) => http.delete(`/api/skills/${id}`)
export const uploadSkill = (files) => {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  return http.post('/api/skills/upload', fd)
}
