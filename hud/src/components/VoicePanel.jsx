import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

function Chip({ ok, children, hint }) {
  return (
    <div className={`kv kv--chip ${ok ? 'is-ok' : 'is-off'}`} title={hint || ''}>
      <span className="dot" />
      <span>{children}</span>
    </div>
  )
}

export default function VoicePanel({ voice, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [state, setVoiceState] = useState(voice)

  useEffect(() => setVoiceState(voice), [voice])

  async function guard(fn, label) {
    setBusy(true)
    setNote('')
    try {
      await fn()
      const next = await api.voiceStatus()
      setVoiceState(next)
      onChanged?.(next)
    } catch (err) {
      setNote(err.message || String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return (
      <section className="panel">
        <h2 className="panel__title">VOICE</h2>
        <p className="dim">voice status unavailable</p>
      </section>
    )
  }

  const wake = state.wake || {}
  const stt = state.stt || {}
  const tts = state.tts || {}
  const capture = state.capture || {}

  return (
    <section className="panel">
      <h2 className="panel__title">
        VOICE{' '}
        <span className={state.running ? 'badge badge--live' : 'badge'}>{state.running ? 'LIVE' : 'IDLE'}</span>
      </h2>

      <Chip ok={wake.available} hint={wake.missing?.join(', ')}>
        wake: {wake.word || 'hey jarvis'}
      </Chip>
      <Chip ok={stt.available} hint={stt.missing?.join(', ')}>
        stt: {stt.engine} {stt.model ? `(${stt.model})` : ''}
      </Chip>
      <Chip ok={tts.available} hint={tts.missing?.join(', ')}>
        tts: {tts.engine} {tts.voice ? `(${tts.voice})` : ''}
      </Chip>
      <Chip ok={capture.available} hint={capture.missing?.join(', ')}>
        mic: {capture.available ? 'ready' : 'no sounddevice'}
      </Chip>

      <div className="row row--wrap">
        {state.running ? (
          <button className="btn btn--danger" disabled={busy} onClick={() => guard(() => api.voiceStop())}>
            Stop loop
          </button>
        ) : (
          <button className="btn btn--primary" disabled={busy} onClick={() => guard(() => api.voiceStart(true, true))}>
            Start wake loop
          </button>
        )}
        <button
          className="btn"
          disabled={busy || !capture.available}
          onClick={() => guard(() => api.listen(true, false))}
          title="Record one utterance and answer"
        >
          Listen once
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => guard(() => api.speak('Systems nominal. At your service, sir.'))}
        >
          Test voice
        </button>
      </div>
      {note ? <p className="dim small">{note}</p> : null}
    </section>
  )
}
