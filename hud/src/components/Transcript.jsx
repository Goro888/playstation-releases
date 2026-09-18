import React, { useEffect, useRef } from 'react'

export default function Transcript({ messages, busy }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  return (
    <div className="transcript">
      {messages.length === 0 ? (
        <p className="dim transcript__empty">
          Say “Hey JARVIS”, or type below. Try: <code>system status</code> · <code>open chrome</code> ·{' '}
          <code>remember my project is JARVIS</code> · <code>what time is it</code>
        </p>
      ) : null}
      {messages.map((m) => (
        <div key={m.id} className={`bubble bubble--${m.role}`} dir="auto">
          <div className="bubble__who">{m.role === 'user' ? 'YOU' : 'JARVIS'}</div>
          <div className="bubble__text">{m.text}</div>
          {m.meta ? <div className="bubble__meta dim">{m.meta}</div> : null}
        </div>
      ))}
      {busy ? (
        <div className="bubble bubble--assistant bubble--pending" dir="auto">
          <div className="bubble__who">JARVIS</div>
          <div className="typing">
            <span />
            <span />
            <span />
          </div>
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  )
}
