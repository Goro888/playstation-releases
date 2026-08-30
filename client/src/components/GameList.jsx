import React, { useEffect, useState } from 'react';
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:4000';

export default function GameList({ search, platform, page, onPageChange, onOpenDetail, favorites, onToggleFav }) {
  const [games, setGames] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pageSize] = useState(20);

  useEffect(() => {
    let cancelled = false;
    async function fetchGames() {
      setLoading(true);
      try {
        const url = `${API_BASE}/api/games?search=${encodeURIComponent(search)}&platform=${encodeURIComponent(platform)}&page=${page}&page_size=${pageSize}`;
        const r = await fetch(url);
        const j = await r.json();
        if (!cancelled) setGames(j.results || []);
      } catch (err) {
        console.error(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchGames();
    return () => { cancelled = true; };
  }, [search, platform, page, pageSize]);

  return (
    <section className="game-list">
      {loading ? <div>Loading…</div> : (
        <>
          <div className="grid">
            {games.map(g => (
              <article key={g.id} className="card">
                <img src={g.background_image || ''} alt="" />
                <div className="card-body">
                  <h4>{g.name}</h4>
                  <div className="meta">
                    <span>{g.released || '—'}</span>
                    <span>Rating: {g.rating}</span>
                  </div>
                  <div className="actions">
                    <button onClick={() => onOpenDetail(g.id)}>Details</button>
                    <button onClick={() => onToggleFav(g)}>{favorites.find(f => f.id === g.id) ? 'Unfavorite' : 'Favorite'}</button>
                  </div>
                </div>
              </article>
            ))}
          </div>
          <div className="pagination">
            <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Prev</button>
            <span>Page {page}</span>
            <button onClick={() => onPageChange(page + 1)}>Next</button>
          </div>
        </>
      )}
    </section>
  );
}
