import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

export async function listProjects() {
  const { data } = await api.get('/projects')
  return data
}

export async function createProject(payload) {
  const { data } = await api.post('/projects', payload)
  return data
}

export async function getProject(projectId) {
  const { data } = await api.get(`/projects/${projectId}`)
  return data
}

export async function deleteProject(projectId) {
  await api.delete(`/projects/${projectId}`)
}

export async function listDocuments(projectId) {
  const { data } = await api.get(`/projects/${projectId}/documents`)
  return data
}

export async function uploadDocument(projectId, file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post(`/projects/${projectId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      if (onProgress && event.total) {
        onProgress(Math.round((event.loaded * 100) / event.total))
      }
    },
  })
  return data
}

export async function deleteDocument(documentId) {
  await api.delete(`/documents/${documentId}`)
}

export function documentFileUrl(documentId) {
  return `/api/documents/${documentId}/file`
}

export function documentHighlightedUrl(documentId, pageNumber, highlightText) {
  const params = new URLSearchParams({ page: String(pageNumber), text: highlightText || '' })
  return `/api/documents/${documentId}/highlighted?${params.toString()}`
}

export async function sendChatMessage(projectId, question) {
  const { data } = await api.post(`/projects/${projectId}/chat`, { question })
  return data
}

export default api
