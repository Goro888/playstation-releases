import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function ToolsPanel({ onRun }) {
  const [tools, setTools] = useState([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api
      .tools()
      .then((data) => setTools(data.tools || []))
      .catch((err) => console.error(err))
  }, [])

  const visible = tools.filter(
    (t) => !filter || t.name.includes(filter.toLowerCase()) || t.category.includes(filter.toLowerCase())
  )

  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        TOOLS <span className="dim">{visible.length}</span>
      </h2>
      <input
        className="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter tools…"
      />
      <div className="tool-list">
        {visible.map((tool) => (
          <div key={tool.name} className={`tool ${tool.available ? '' : 'tool--off'}`}>
            <div className="tool__head">
              <code>{tool.name}</code>
              <span className={`risk risk--${tool.risk}`}>{tool.risk}</span>
            </div>
            <p className="tool__desc">{tool.description}</p>
            <div className="tool__foot">
              <span className="tag">{tool.category}</span>
              {!tool.required_params?.length ? (
                <button
                  className="btn btn--ghost"
                  onClick={() => onRun?.(tool.name, {})}
                  title="Run with no arguments"
                >
                  run
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
