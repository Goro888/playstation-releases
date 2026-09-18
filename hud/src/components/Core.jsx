import React, { useEffect, useRef } from 'react'

const STATES = {
  idle: { label: 'STANDBY', intensity: 0.12, color: '#5eead4' },
  listening: { label: 'LISTENING', intensity: 0.9, color: '#38bdf8' },
  transcribing: { label: 'TRANSCRIBING', intensity: 0.45, color: '#a78bfa' },
  planning: { label: 'PLANNING', intensity: 0.5, color: '#facc15' },
  thinking: { label: 'THINKING', intensity: 0.7, color: '#f59e0b' },
  acting: { label: 'ACTING', intensity: 0.8, color: '#fb7185' },
  speaking: { label: 'SPEAKING', intensity: 0.75, color: '#4ade80' },
  error: { label: 'ERROR', intensity: 0.3, color: '#ef4444' }
}

function Waveform({ state, level = 0 }) {
  const barsRef = useRef([])
  const BARS = 56
  const config = STATES[state] || STATES.idle

  useEffect(() => {
    let raf = 0
    let t = 0
    const phases = Array.from({ length: BARS }, (_, i) => Math.random() * Math.PI * 2)

    const tick = () => {
      t += 0.06
      const base = config.intensity * (0.55 + level * 0.9)
      barsRef.current.forEach((bar, i) => {
        if (!bar) return
        const wave = Math.sin(t * 1.6 + phases[i]) * 0.5 + 0.5
        const noise = Math.sin(t * 3.1 + phases[i] * 2.3) * 0.5 + 0.5
        const h = 4 + (wave * 0.6 + noise * 0.4) * base * 46
        bar.style.height = `${Math.max(3, h)}px`
        bar.style.opacity = `${0.35 + Math.min(1, base * 1.4) * 0.65}`
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [config.intensity, level])

  return (
    <div className="waveform" aria-hidden="true">
      {Array.from({ length: BARS }).map((_, i) => (
        <span
          key={i}
          ref={(el) => {
            barsRef.current[i] = el
          }}
          style={{ background: config.color }}
        />
      ))}
    </div>
  )
}

export default function Core({ state = 'idle', level = 0, backend = '', model = '', session = '' }) {
  const config = STATES[state] || STATES.idle
  return (
    <div className={`core core--${state}`} style={{ '--accent': config.color }}>
      <svg className="core__svg" viewBox="0 0 260 260" role="img" aria-label={`JARVIS ${config.label}`}>
        <defs>
          <radialGradient id="coreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={config.color} stopOpacity="0.55" />
            <stop offset="55%" stopColor={config.color} stopOpacity="0.12" />
            <stop offset="100%" stopColor={config.color} stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle className="core__glow" cx="130" cy="130" r="118" fill="url(#coreGlow)" />
        <circle className="core__ring core__ring--outer" cx="130" cy="130" r="116" />
        <circle className="core__ring core__ring--mid" cx="130" cy="130" r="96" />
        <circle className="core__ring core__ring--dashed" cx="130" cy="130" r="78" />
        <circle className="core__ring core__ring--inner" cx="130" cy="130" r="58" />
        <circle className="core__pulse" cx="130" cy="130" r="44" />
        <text x="130" y="126" className="core__label" textAnchor="middle">
          JARVIS
        </text>
        <text x="130" y="146" className="core__state" textAnchor="middle">
          {config.label}
        </text>
      </svg>
      <Waveform state={state} level={level} />
      <div className="core__meta">
        <span>{backend || 'offline'}</span>
        <span className="dim">{model}</span>
        {session ? <span className="dim">· {session}</span> : null}
      </div>
    </div>
  )
}
