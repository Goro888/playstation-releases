const express = require('express');
const router = express.Router();
const axios = require('axios');
const { getCached, setCached, getAllCached } = require('../db');
const stringify = require('csv-stringify').stringify;

const RAWG_BASE = 'https://api.rawg.io/api';
const RAWG_KEY = process.env.RAWG_API_KEY || '';
const CACHE_TTL = parseInt(process.env.CACHE_TTL_SECONDS || '86400', 10);

// map simple platform slug -> name fragment to match RAWG platform names
const PLATFORM_MAP = {
  all: null,
  ps5: 'PlayStation 5',
  ps4: 'PlayStation 4',
  ps3: 'PlayStation 3',
  ps2: 'PlayStation 2',
  ps1: 'PlayStation',
  psp: 'PSP',
  'ps-vita': 'PS Vita'
};

function rawgFetch(path, params = {}) {
  const url = `${RAWG_BASE}${path}`;
  const p = { ...params };
  if (RAWG_KEY) p.key = RAWG_KEY;
  return axios.get(url, { params: p }).then(r => r.data);
}

function isPlaystationOnGame(game, platformFilter) {
  if (!game.platforms) return false;
  if (!platformFilter) {
    // any PlayStation in name
    return game.platforms.some(p => /playstation|psp|ps vita/i.test(p.platform.name));
  }
  const frag = PLATFORM_MAP[platformFilter];
  return game.platforms.some(p => p.platform.name.toLowerCase().includes((frag || '').toLowerCase()));
}

router.get('/', async (req, res) => {
  try {
    const search = req.query.search || '';
    const platform = (req.query.platform || 'all').toLowerCase();
    const page = parseInt(req.query.page || '1', 10);
    const page_size = Math.min(parseInt(req.query.page_size || '20', 10), 40);

    // Fetch from RAWG - use RAWG search & paging; filter client-side by platform name if needed
    const data = await rawgFetch('/games', { search, page, page_size });
    let results = data.results || [];

    // filter to PlayStation if platform != 'all'
    if (platform !== 'all') {
      results = results.filter(g => isPlaystationOnGame(g, platform));
    } else {
      results = results.filter(g => isPlaystationOnGame(g, null));
    }

    // cache each returned game
    results.forEach(g => {
      if (g.id) setCached(g.id, g);
    });

    res.json({
      count: results.length,
      next: data.next,
      previous: data.previous,
      results
    });
  } catch (err) {
    console.error(err && err.response ? err.response.data : err);
    res.status(500).json({ error: 'Failed to fetch games' });
  }
});

router.get('/:id', async (req, res) => {
  try {
    const id = parseInt(req.params.id, 10);
    const cached = getCached(id);
    const now = Math.floor(Date.now() / 1000);
    if (cached && (now - cached.fetched_at) < CACHE_TTL) {
      return res.json({ fromCache: true, data: cached.data });
    }
    // fetch details from RAWG
    const data = await rawgFetch(`/games/${id}`);
    setCached(id, data);
    res.json({ fromCache: false, data });
  } catch (err) {
    console.error(err && err.response ? err.response.data : err);
    res.status(500).json({ error: 'Failed to fetch details' });
  }
});

router.get('/export/csv', async (req, res) => {
  try {
    // Export cached PlayStation games filtered by query params (simple approach)
    const platform = (req.query.platform || 'all').toLowerCase();
    const search = (req.query.search || '').toLowerCase();

    const all = getAllCached().map(r => r.data);
    let filtered = all.filter(g => {
      // must be PlayStation
      const isPS = g.platforms && g.platforms.some(p => /playstation|psp|ps vita/i.test(p.platform.name));
      if (!isPS) return false;
      if (platform && platform !== 'all') {
        const frag = PLATFORM_MAP[platform];
        if (!g.platforms.some(p => p.platform.name.toLowerCase().includes((frag || '').toLowerCase()))) return false;
      }
      if (search) {
        return (g.name || '').toLowerCase().includes(search);
      }
      return true;
    });

    // Create CSV rows
    const rows = filtered.map(g => ({
      id: g.id,
      name: g.name,
      released: g.released || '',
      platforms: (g.platforms || []).map(p => p.platform.name).join('; '),
      rating: g.rating || '',
      rawg_slug: g.slug || ''
    }));

    res.setHeader('Content-Disposition', 'attachment; filename=ps_games_export.csv');
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');

    stringify(rows, { header: true }, (err, out) => {
      if (err) return res.status(500).send('CSV generation failed');
      res.send(out);
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to export' });
  }
});

module.exports = router;
