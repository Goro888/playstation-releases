import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, subscribeEvents } from './api.js'
import Core from './components/Core.jsx'
import SystemMonitor from './components/SystemMonitor.jsx'
import ActivityFeed from './components/ActivityFeed.jsx'
import Permissions from './components/Permissions.jsx'
import MemoryPanel from './components/MemoryPanel.jsx'
import VoicePanel from './components/VoicePanel.jsx'
import ToolsPanel from './components/ToolsPanel.jsx'
import Transcript from './components/Transcript.jsx'

const uid = () => Math.random().toString(36).slice(2, 10)
const QUICK = [
  'system status',
  'what time is it',
  'list the files in this folder',
  'take a screenshot',
  'list my tasks'
]

export default function App() {
  const [status, setStatus] = useState(null)
  const [system, setSystem] = useState(null)
  const [voice, setVoice] = useState(null)
  const [events, setEvents] = useState([])
  const [messages, setMessages] = useState([])
  const [pending, setPending] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [state, setState] = useState('idle')
  const [level, setLevel] = useState(0)
  const [tab, setTab] = useState('activity')
  const [sse, setSse] = useState('connecting')
  const [error, setError] = useState('')

  const busyRef = useRef(false)
  busyRef.current = busy

  const refreshStatus = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([api.status(), api.voiceStatus()])
      setStatus(s)
      setVoice(v)
    } catch {
      setSse('offline')
    }
  }, [])

  const refreshPermissions = useCallback(async () => {
    try {
      const data = await api.permissions()
      setPending(data.pending || [])
    } catch {
      /* ignore */
    }
  }, [])

  // initial load + polling
  useEffect(() => {
    refreshStatus()
    refreshPermissions()
    api
      .conversation('hud')
      .then((data) =>
        setMessages(
          (data.messages || []).map((m) => ({
            id: uid(),
            role: m.role === 'assistant' ? 'assistant' : 'user',
            text: m.content
          }))
        )
      )
      .catch(() => {})
    const sysTimer = setInterval(() => {
      api.system().then(setSystem).catch(() => {})
      refreshPermissions()
    }, 2000)
    const statusTimer = setInterval(refreshStatus, 15000)
    return () => {
      clearInterval(sysTimer)
      clearInterval(statusTimer)
    }
  }, [refreshStatus, refreshPermissions])

  // live event stream
  useEffect(() => {
    return subscribeEvents(
      (event) => {
        setEvents((prev) => [...prev.slice(-199), event])
        const p = event.payload || {}
        switch (event.type) {
          case 'status':
            if (p.state) setState(p.state)
            break
          case 'audio_level':
            setLevel(Number(p.level) || 0)
            break
          case 'message':
            setState('idle')
            if (!busyRef.current && p.text) {
              setMessages((prev) => [...prev, { id: uid(), role: 'assistant', text: p.text }])
            }
            break
          case 'transcript':
            if (p.text) setMessages((prev) => [...prev, { id: uid(), role: 'user', text: p.text }])
            break
          case 'permission_request':
          case 'permission_granted':
          case 'permission_denied':
          case 'permission_expired':
            refreshPermissions()
            break
          case 'error':
            setError(p.message || 'error')
            break
          default:
            break
        }
      },
      (conn) => setSse(conn)
    )
  }, [refreshPermissions])

  async function send(text) {
    const value = (text ?? input).trim()
    if (!value || busy) return
    setInput('')
    setError('')
    setMessages((prev) => [...prev, { id: uid(), role: 'user', text: value }])
    setBusy(true)
    setState('planning')
    try {
      const res = await api.chat(value, 'hud')
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: 'assistant',
          text: res.reply || '(no reply)',
          meta: `${res.backend || 'offline'}${res.model ? ` · ${res.model}` : ''} · ${res.steps} step(s) · ${res.duration}s`
        }
      ])
    } catch (err) {
      setError(err.message || String(err))
      setMessages((prev) => [...prev, { id: uid(), role: 'assistant', text: `⚠ ${err.message || err}` }])
    } finally {
      setBusy(false)
      setState('idle')
      setLevel(0)
      refreshPermissions()
    }
  }

  async function runTool(name, args) {
    setError('')
    try {
      const res = await api.callTool(name, args)
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: 'assistant',
          text: `${name}: ${res.ok ? res.output : res.error || res.output}`,
          meta: `tool result · ${res.ok ? 'ok' : 'failed'}`
        }
      ])
      refreshPermissions()
    } catch (err) {
      setError(err.message || String(err))
    }
  }

  const brain = status?.local?.ok ? 'local' : status?.cloud?.ok ? 'cloud' : 'offline'
  const brainLabel =
    brain === 'local'
      ? `LOCAL · ${status?.local?.model || ''}`
      : brain === 'cloud'
        ? `CLOUD · ${status?.cloud?.model || ''}`
        : 'OFFLINE BRAIN'

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark">◈</span>
          <div>
            <h1>JARVIS</h1>
            <p className="dim small">local-first operating assistant</p>
          </div>
        </div>
        <div className="chips">
          <span className={`chip chip--${brain}`}>{brainLabel}</span>
          <span className="chip">mode: {status?.mode || '…'}</span>
          <span className="chip">tools: {status?.tools?.count ?? '…'}</span>
          <span className="chip">mem: {status?.memory?.facts ?? '…'}</span>
          <span className={`chip chip--${sse === 'live' ? 'ok' : 'warn'}`}>stream: {sse}</span>
        </div>
      </header>

      {error ? (
        <div className="banner" onClick={() => setError('')}>
          {error} <span className="dim">(click to dismiss)</span>
        </div>
      ) : null}

      <main className="grid">
        <aside className="col col--left">
          <SystemMonitor data={system} />
          <VoicePanel voice={voice} onChanged={setVoice} />
        </aside>

        <section className="col col--center">
          <Core
            state={state}
            level={level}
            backend={brain}
            model={status?.local?.ok ? status?.local?.model : status?.cloud?.model}
          />
          <Permissions requests={pending} onResolved={refreshPermissions} />
          <Transcript messages={messages} busy={busy} />
          <div className="quick">
            {QUICK.map((q) => (
              <button key={q} className="btn btn--ghost" disabled={busy} onClick={() => send(q)}>
                {q}
              </button>
            ))}
          </div>
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault()
              send()
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Speak or type a command…  (/cloud forces the cloud tier)"
              dir="auto"
              disabled={busy}
            />
            <button className="btn btn--primary" type="submit" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
        </section>

        <aside className="col col--right">
          <nav className="tabs">
            {[
              ['activity', 'ACTIVITY'],
              ['memory', 'MEMORY'],
              ['tools', 'TOOLS']
            ].map(([key, label]) => (
              <button
                key={key}
                className={`tab ${tab === key ? 'tab--active' : ''}`}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </nav>
          {tab === 'activity' ? <ActivityFeed events={events} /> : null}
          {tab === 'memory' ? <MemoryPanel stats={status?.memory} /> : null}
          {tab === 'tools' ? <ToolsPanel onRun={runTool} /> : null}
        </aside>
      </main>

      <footer className="footer dim small">
        {status?.system ? `${status.system} · ` : ''}
        {status?.config_path ? `config: ${status.config_path} · ` : ''}
        everything runs on this machine unless you route a request to the cloud tier
      </footer>
    </div>
  )
}
