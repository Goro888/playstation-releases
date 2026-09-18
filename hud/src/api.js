// Thin client for the JARVIS bridge. Everything is relative to '/api', which
// Vite proxies to the Python bridge — so the HUD works unchanged on Windows
// (localhost) and through a preview tunnel.
const API = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || body.error || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  status: () => request('/status'),
  system: () => request('/system'),
  tools: () => request('/tools'),
  config: () => request('/config'),

  conversation: (session = 'default') => request(`/conversation?session=${encodeURIComponent(session)}`),
  history: (limit = 50) => request(`/history?limit=${limit}`),

  chat: (message, session = 'default', force = null) =>
    request('/chat', {
      method: 'POST',
      body: JSON.stringify({ message, session, force })
    }),

  callTool: (name, args = {}) => request('/tools/call', { method: 'POST', body: JSON.stringify({ name, args }) }),

  permissions: () => request('/permissions'),
  resolve: (id, approve, remember = false) =>
    request(`/permissions/${id}/${approve ? 'approve' : 'deny'}${remember ? '?remember=true' : ''}`, { method: 'POST' }),

  memory: (q = '') => request(`/memory?q=${encodeURIComponent(q)}`),
  remember: (content, kind = 'note', importance = 3) =>
    request('/memory', { method: 'POST', body: JSON.stringify({ content, kind, importance }) }),
  forget: (id) => request(`/memory/${id}`, { method: 'DELETE' }),

  tasks: (status = 'open') => request(`/tasks?status=${status}`),
  addTask: (title, notes = '') => request('/tasks', { method: 'POST', body: JSON.stringify({ title, notes }) }),
  completeTask: (id) => request(`/tasks/${id}/done`, { method: 'POST' }),

  voiceStatus: () => request('/voice/status'),
  voiceStart: (speak = true, wakeWord = true) =>
    request('/voice/start', { method: 'POST', body: JSON.stringify({ speak, wake_word: wakeWord }) }),
  voiceStop: () => request('/voice/stop', { method: 'POST' }),
  speak: (text) => request('/voice/speak', { method: 'POST', body: JSON.stringify({ text }) }),
  listen: (respond = true, speak = true) =>
    request('/voice/listen', { method: 'POST', body: JSON.stringify({ respond, speak }) })
}

// Server-sent events: status changes, tool calls, permission requests, answers.
export function subscribeEvents(onEvent, onStatus) {
  const source = new EventSource(`${API}/events`)
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onEvent(data)
    } catch {
      /* keep-alive or malformed frame */
    }
  }
  source.onerror = () => onStatus?.('reconnecting')
  source.onopen = () => onStatus?.('live')
  return () => source.close()
}
