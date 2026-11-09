import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 送 token
http.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

// 统一 401 处理：清会话并跳回登录页（避免用户停留在"权限被拉空"的中间态）
http.interceptors.response.use(
  (r) => r.data,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (!window.location.hash.startsWith('#/login')) {
        window.location.hash = '#/login'
      }
    }
    return Promise.reject(err)
  }
)

// 用药记录（处方）
export const medApi = {
  list: (params) => http.get('/med-records', { params }),
  create: (data) => http.post('/med-records', data),
  update: (id, data) => http.put(`/med-records/${id}`, data),
  get: (id) => http.get(`/med-records/${id}`),
  remove: (id) => http.delete(`/med-records/${id}`),
  batchRemove: (ids) => http.post('/med-records/batch-delete', ids),
  count: () => http.get('/med-records/total-count'),
}

// 认证
export const authApi = {
  login: (data) => http.post('/auth/login', data),
  me: () => http.get('/auth/me'),
  updateProfile: (data) => http.put('/auth/profile', data),
  changePassword: (data) => http.post('/auth/change-password', data),
  loginLogs: (params) => http.get('/auth/login-logs', { params }),
  myPermissions: () => http.get('/auth/my-permissions'),
  uploadAvatar: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/auth/avatar', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  uploadAvatarJson: (data) => http.post('/auth/avatar-json', data),
  removeAvatar: () => http.delete('/auth/avatar'),
}

// 角色 / 权限管理
export const roleApi = {
  list: () => http.get('/roles'),
  create: (data) => http.post('/roles', data),
  update: (code, data) => http.put(`/roles/${code}`, data),
  remove: (code) => http.delete(`/roles/${code}`),
  permDefs: () => http.get('/permissions'),
}

// 系统设置
export const settingsApi = {
  get: () => http.get('/settings'),
  save: (data) => http.put('/settings', data),
}

// 用户管理
export const userApi = {
  list: (params) => http.get('/users', { params }),
  create: (data) => http.post('/users', data),
  update: (id, data) => http.put(`/users/${id}`, data),
  remove: (id) => http.delete(`/users/${id}`),
}

// 报告模板
export const tplApi = {
  list: (params) => http.get('/templates', { params }),
  get: (id) => http.get(`/templates/${id}`),
  create: (data) => http.post('/templates', data),
  update: (id, data) => http.put(`/templates/${id}`, data),
  remove: (id) => http.delete(`/templates/${id}`),
  batchRemove: (ids) => http.post('/templates/batch-delete', ids),
  count: () => http.get('/templates/total-count'),
}

// 检查报告
export const reportApi = {
  list: (params) => http.get('/reports', { params }),
  get: (id) => http.get(`/reports/${id}`),
  create: (data) => http.post('/reports', data),
  update: (id, data) => http.put(`/reports/${id}`, data),
  remove: (id) => http.delete(`/reports/${id}`),
  batchRemove: (ids) => http.post('/reports/batch-delete', ids),
  count: () => http.get('/reports/total-count'),
  docNames: () => http.get('/reports/doc-names'),
  trend: (name, scope) => http.get('/reports/trend', { params: { name, scope } }),
  latestDocs: (limit) => http.get('/reports/latest-docs', { params: { limit } }),
  interests: () => http.get('/reports/interests'),
  interestAdd: (name, docId) => http.post('/reports/interests', { name, doc_id: docId || null }),
  interestRemove: (name, docId) => http.delete('/reports/interests', { params: { name, doc_id: docId || undefined } }),
  ocr: (formData) => http.post('/reports/ocr', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 180000 }),
  // OCR（JSON + base64，规避部分网络对 multipart 上传的拦截）
  ocrJson: (data) => http.post('/reports/ocr-json', data, { timeout: 180000 }),
  // 报告（子级）
  docs: (rid) => http.get(`/reports/${rid}/docs`),
  docCreate: (rid, data) => http.post(`/reports/${rid}/docs`, data),
  docUpdate: (rid, did, data) => http.put(`/reports/${rid}/docs/${did}`, data),
  docRemove: (rid, did) => http.delete(`/reports/${rid}/docs/${did}`),
  docImage: (rid, did, formData) => http.post(`/reports/${rid}/docs/${did}/image`, formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }),
  docImageJson: (rid, did, data) => http.post(`/reports/${rid}/docs/${did}/image-json`, data, { timeout: 60000 }),
  docAttach: (rid, did, formData) => http.post(`/reports/${rid}/docs/${did}/attach`, formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }),
  docAttachJson: (rid, did, data) => http.post(`/reports/${rid}/docs/${did}/attach-json`, data, { timeout: 60000 }),
  docAttachRemove: (rid, did, idx) => http.delete(`/reports/${rid}/docs/${did}/attach/${idx}`),
}

// AI 模型配置
export const aiApi = {
  list: (params) => http.get('/ai-models', { params }),
  create: (data) => http.post('/ai-models', data),
  update: (id, data) => http.put(`/ai-models/${id}`, data),
  remove: (id) => http.delete(`/ai-models/${id}`),
  batchRemove: (ids) => http.post('/ai-models/batch-delete', ids),
  count: () => http.get('/ai-models/total-count'),
  fetchModels: (data) => http.post('/ai-models/fetch-models', data, { timeout: 60000 }),
}

// AI 能力（报告分析 + 问数助手）
export const aiApi2 = {
  analyzeReport: (data) => http.post('/ai/analyze-report', data, { timeout: 180000 }),
  listAnalyses: (params) => http.get('/ai/analyses', { params }),
  deleteAnalysis: (id) => http.delete(`/ai/analyses/${id}`),
  agentChat: (data) => http.post('/ai/agent-chat', data, { timeout: 180000 }),
  // 流式问数（SSE）：onEvent 收到 web_search / done / error 事件
  agentChatStream: (data, onEvent) => {
    return new Promise((resolve, reject) => {
      fetch('/api/ai/agent-chat-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + (localStorage.getItem('token') || ''),
        },
        body: JSON.stringify(data),
      }).then(async (resp) => {
        if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status)
        const reader = resp.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          let i
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2)
            const line = chunk.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            let evt
            try { evt = JSON.parse(line.slice(5).trim()) } catch { continue }
            if (evt.type === 'error') { reject(new Error(evt.message || 'AI 服务出错')); return }
            onEvent(evt)
          }
        }
        resolve()
      }).catch((e) => reject(e))
    })
  },
  webFetch: (url) => http.post('/ai/web-fetch', { url }, { timeout: 30000 }),
  agentExecute: (data) => http.post('/ai/agent-execute', data, { timeout: 60000 }),
  agentCompact: (data) => http.post('/ai/agent-compact', data, { timeout: 120000 }),
  // 后台任务式问数：创建任务立即返回；任务在服务器端持续执行，刷新/离开页面不中断
  createAgentTask: (data) => http.post('/ai/agent-chat-task', data, { timeout: 15000 }),
  cancelAgentTask: (taskId) => http.post(`/ai/agent-chat-task/${taskId}/cancel`, {}, { timeout: 15000 }),
  // 订阅任务进度（SSE，GET）：终态（done/cancelled/error）后流自动结束
  agentTaskStream: (taskId, onEvent) => {
    let stop
    const stream = new Promise((resolve, reject) => {
      const ctrl = new AbortController()
      stop = () => ctrl.abort()
      fetch(`/api/ai/agent-chat-task/${taskId}/stream`, {
        headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') },
        signal: ctrl.signal,
      }).then(async (resp) => {
        if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status)
        const reader = resp.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          let r
          try { r = await reader.read() } catch (e) { if (ctrl.signal.aborted) { resolve(); return } console.error('[SSE]READ_ERR', taskId, e && e.message); throw e }
          if (r.done) break
          buf += dec.decode(r.value, { stream: true })
          let i
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2)
            const line = chunk.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            let evt
            try { evt = JSON.parse(line.slice(5).trim()) } catch { continue }
            // 单事件容错：onEvent 抛错（如持久化异常）只丢该事件，
            // 不停掉整条流（否则后续 delta 全部丢失且触发重连风暴）
            try {
              if (evt.type === 'error') { onEvent(evt); resolve(); return }
              if (evt.type === 'done' || evt.type === 'cancelled') { onEvent(evt); resolve(); return }
              onEvent(evt)
            } catch (e) {
              console.error('[SSE]EVT_ERR', taskId, evt && evt.type, String((e && e.stack) || e))
              if (evt.type === 'error' || evt.type === 'done' || evt.type === 'cancelled') resolve()
            }
          }
        }
        resolve()
      }).catch((e) => {
        if (ctrl.signal.aborted) resolve()
        else { console.error('[SSE]REJECT', taskId, String((e && e.message) || e)); reject(e) }
      })
    })
    return { stream, stop }
  },
  listSkills: () => http.get('/ai/skills'),
  installSkill: (formData) => http.post('/ai/skills/install', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }),
  getSessions: () => http.get('/ai/sessions'),
  saveSessions: (data) => http.post('/ai/sessions', data, { timeout: 20000 }),
}

// 文件存储
export const fileApi = {
  list: (params) => http.get('/files', { params }),
  upload: (formData) => http.post('/files', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 }),
  uploadJson: (data) => http.post('/files-json', data, { timeout: 120000 }),
  download: (id) => http.get(`/files/${id}/download`, { responseType: 'blob' }),
  remove: (id) => http.delete(`/files/${id}`),
  batchRemove: (ids) => http.post('/files/batch-delete', ids),
  newFolder: (data) => http.post('/files/new-folder', data),
  count: () => http.get('/files/total-count'),
}

export default http