import React from 'react'

function Bar({ label, value, suffix = '%', detail = '' }) {
  const pct = Math.max(0, Math.min(100, value))
  const tone = pct > 85 ? 'danger' : pct > 65 ? 'warn' : 'ok'
  return (
    <div className="meter">
      <div className="meter__head">
        <span>{label}</span>
        <span className="meter__value">
          {pct.toFixed(0)}
          {suffix}
        </span>
      </div>
      <div className="meter__track">
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${pct}%` }} />
      </div>
      {detail ? <div className="meter__detail dim">{detail}</div> : null}
    </div>
  )
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

export default function SystemMonitor({ data }) {
  if (!data) {
    return (
      <section className="panel">
        <h2 className="panel__title">SYSTEM</h2>
        <p className="dim">telemetry offline</p>
      </section>
    )
  }
  return (
    <section className="panel">
      <h2 className="panel__title">SYSTEM</h2>
      <Bar
        label="CPU"
        value={data.cpu_percent}
        detail={`${data.per_cpu?.length || 0} cores · ${data.processes} processes`}
      />
      <Bar
        label="MEMORY"
        value={data.ram_percent}
        detail={`${data.ram_used_gb} / ${data.ram_total_gb} GB`}
      />
      <Bar label="DISK" value={data.disk_percent} detail={`${data.disk_free_gb} GB free`} />
      <div className="kv">
        <span className="dim">uptime</span>
        <span>{formatUptime(data.uptime)}</span>
      </div>
      <div className="kv">
        <span className="dim">net</span>
        <span>
          ↓{data.net_recv_mb} MB · ↑{data.net_sent_mb} MB
        </span>
      </div>
      <div className="kv">
        <span className="dim">host</span>
        <span className="truncate">{data.platform}</span>
      </div>
    </section>
  )
}
