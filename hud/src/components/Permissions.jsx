import React, { useState } from 'react'
import { api } from '../api.js'

export default function Permissions({ requests, onResolved }) {
  const [busy, setBusy] = useState(null)

  async function resolve(id, approve, remember = false) {
    setBusy(id)
    try {
      await api.resolve(id, approve, remember)
      onResolved?.()
    } catch (err) {
      console.error(err)
    } finally {
      setBusy(null)
    }
  }

  if (!requests.length) return null

  return (
    <section className="panel panel--alert">
      <h2 className="panel__title">CONFIRMATION REQUIRED</h2>
      {requests.map((req) => (
        <div key={req.id} className="permission">
          <div className="permission__head">
            <strong>{req.tool}</strong>
            <span className={`risk risk--${req.risk}`}>{req.risk}</span>
          </div>
          <p className="permission__reason">{req.reason}</p>
          <pre className="permission__args">{JSON.stringify(req.args, null, 1)}</pre>
          <div className="permission__actions">
            <button className="btn btn--ok" disabled={busy === req.id} onClick={() => resolve(req.id, true, true)}>
              Allow always
            </button>
            <button className="btn btn--primary" disabled={busy === req.id} onClick={() => resolve(req.id, true)}>
              Allow once
            </button>
            <button className="btn btn--danger" disabled={busy === req.id} onClick={() => resolve(req.id, false)}>
              Deny
            </button>
          </div>
        </div>
      ))}
    </section>
  )
}
