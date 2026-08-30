import React, { useEffect, useState } from 'react';
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:4000';

export default function GameDetail({ id, onClose, onToggleFav, favorites }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch(`${API_BASE}/api/games/${id}`);
        const j = await r.json();
        if (!cancelled) setData(j.data || j);
      } catch (err) {
        console.error(err);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [id]);

  if (!data) return (
    <div className="modal">
      <div className="modal-body">
        <button onClick={onClose}>Close</button>
        <div>Loading...</div>
      </div>
    </div>
  );

  const isFav = favorites.find(f => f.id === data.id);
  return (
    <div className="modal">
      <div className="modal-body">
        <button className="close" onClick={onClose}>✕</button>
        <h2>{data.name}</h2>
        <p><strong>Released:</strong> {data.released}</p>
        <p><strong>Platforms:</strong> {(data.platforms || []).map(p => p.platform.name).join(', ')}</p>
        <p><strong>Rating:</strong> {data.rating}</p>
        <div dangerouslySetInnerHTML={{ __html: data.description || '<em>No description</em>' }} />
        {data.short_screenshots && data.short_screenshots.length > 0 && (
          <div className="screenshots">
            {data.short_screenshots.map(s => <img key={s.id} src={s.image} alt="" />)}
          </div>
        )}
        <div className="modal-actions">
          <button onClick={() => onToggleFav(data)}>{isFav ? 'Unfavorite' : 'Favorite'}</button>
        </div>
      </div>
    </div>
  );
}
