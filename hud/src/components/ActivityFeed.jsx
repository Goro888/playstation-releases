import React from 'react'

const ICONS = {
  tool_call: '→',
  tool_result: '←',
  permission_request: '!',
  message: '●',
  error: '✕',
  route: '⇄',
  transcript: '🎙',
  memory_added: '◆',
  status: '◦'
}

function formatArgs(args) {
  if (!args) return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}=${String(v).slice(0, 40)}`)
    .join(', ')
}

function describe(event) {
  const p = event.payload || {}
  switch (event.type) {
    case 'tool_call':
      return `${p.tool}(${formatArgs(p.args)})`
    case 'tool_result': {
      const out = String(p.output ?? '').replace(/\s+/g, ' ').slice(0, 160)
      return `${p.tool}: ${p.ok ? '' : 'FAILED '}${out}`
    }
    case 'permission_request':
      return `confirm ${p.tool} [${p.risk}] — ${p.reason}`
    case 'route':
      return `route → ${p.backend} (${p.reason})`
    case 'status':
      return p.state ? `state: ${p.state}${p.tool ? ` · ${p.tool}` : ''}` : ''
    case 'error':
      return p.message || 'error'
    case 'transcript':
      return `heard: ${p.text}`
    default:
      return JSON.stringify(p).slice(0, 160)
  }
}

export default function ActivityFeed({ events }) {
  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        ACTIVITY <span className="dim">{events.length}</span>
      </h2>
      <div className="feed">
        {events.length === 0 ? <p className="dim">no activity yet</p> : null}
        {events
          .slice()
          .reverse()
          .map((event) => (
            <div key={event.id} className={`feed__row feed__row--${event.type}`}>
              <span className="feed__icon">{ICONS[event.type] || '·'}</span>
              <span className="feed__text">{describe(event)}</span>
              <span className="feed__time">
                {new Date(event.ts * 1000).toLocaleTimeString([], { hour12: false })}
              </span>
            </div>
          ))}
      </div>
    </section>
  )
}
