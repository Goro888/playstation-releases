import React, { useState, useEffect } from 'react';
import GameList from './components/GameList';
import GameDetail from './components/GameDetail';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:4000';

export default function App() {
  const [platform, setPlatform] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);
  const [favorites, setFavorites] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('ps-favs') || '[]');
    } catch {
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem('ps-favs', JSON.stringify(favorites));
  }, [favorites]);

  function toggleFav(game) {
    setFavorites(prev => {
      if (prev.find(g => g.id === game.id)) return prev.filter(g => g.id !== game.id);
      return [...prev, { id: game.id, name: game.name, released: game.released }];
    });
  }

  function onExportCSV() {
    const url = `${API_BASE}/api/games/export/csv?platform=${encodeURIComponent(platform)}&search=${encodeURIComponent(search)}`;
    window.open(url, '_blank');
  }

  return (
    <div className="app">
      <header>
        <h1>PlayStation Releases</h1>
        <div className="controls">
          <input
            placeholder="Search games..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
          />
          <select value={platform} onChange={e => { setPlatform(e.target.value); setPage(1); }}>
            <option value="all">All PlayStation</option>
            <option value="ps5">PS5</option>
            <option value="ps4">PS4</option>
            <option value="ps3">PS3</option>
            <option value="ps2">PS2</option>
            <option value="ps1">PS1</option>
            <option value="psp">PSP</option>
            <option value="ps-vita">PS Vita</option>
          </select>
          <button onClick={onExportCSV}>Export CSV</button>
        </div>
      </header>

      <main>
        <GameList
          search={search}
          platform={platform}
          page={page}
          onPageChange={setPage}
          onOpenDetail={id => setSelected(id)}
          favorites={favorites}
          onToggleFav={toggleFav}
        />
        <aside className="favorites">
          <h3>Favorites</h3>
          {favorites.length === 0 ? <div>No favorites</div> : (
            <ul>
              {favorites.map(f => <li key={f.id}>{f.name} ({f.released || '—'})</li>)}
            </ul>
          )}
        </aside>
        {selected && <GameDetail id={selected} onClose={() => setSelected(null)} onToggleFav={toggleFav} favorites={favorites} />}
      </main>
      <footer>
        <small>Data source: RAWG.io</small>
      </footer>
    </div>
  );
}
