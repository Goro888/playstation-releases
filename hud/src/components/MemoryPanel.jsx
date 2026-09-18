import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function MemoryPanel({ stats }) {
  const [query, setQuery] = useState('')
  const [facts, setFacts] = useState([])
  const [tasks, setTasks] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  async function load(q = query) {
    try {
      const [mem, taskList] = await Promise.all([api.memory(q), api.tasks('open')])
      setFacts(mem.facts || [])
      setTasks(taskList.tasks || [])
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    load('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function remember(e) {
    e.preventDefault()
    const content = draft.trim()
    if (!content) return
    setBusy(true)
    try {
      await api.remember(content)
      setDraft('')
      await load('')
    } finally {
      setBusy(false)
    }
  }

  async function forget(id) {
    await api.forget(id)
    await load()
  }

  async function doneTask(id) {
    await api.completeTask(id)
    await load()
  }

  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        MEMORY {stats ? <span className="dim">{stats.facts} facts</span> : null}
      </h2>

      <form className="row" onSubmit={remember}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Store a fact…"
          dir="auto"
        />
        <button className="btn btn--primary" disabled={busy || !draft.trim()}>
          Save
        </button>
      </form>

      <input
        className="search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          load(e.target.value)
        }}
        placeholder="Search memory…"
        dir="auto"
      />

      <div className="mem-list">
        {facts.length === 0 ? <p className="dim">nothing stored yet</p> : null}
        {facts.map((f) => (
          <div key={f.id} className="mem-item">
            <div className="mem-item__body" dir="auto">
              <span className="tag">{f.kind}</span> {f.content}
            </div>
            <button className="btn btn--ghost" onClick={() => forget(f.id)} title="forget">
              ✕
            </button>
          </div>
        ))}
      </div>

      <h3 className="panel__sub">TASKS</h3>
      <div className="mem-list">
        {tasks.length === 0 ? <p className="dim">no open tasks</p> : null}
        {tasks.map((t) => (
          <div key={t.id} className="mem-item">
            <div className="mem-item__body" dir="auto">
              <span className="tag tag--task">#{t.id}</span> {t.title}
            </div>
            <button className="btn btn--ghost" onClick={() => doneTask(t.id)} title="complete">
              ✓
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
