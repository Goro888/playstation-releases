const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const DB_DIR = path.resolve(__dirname, 'data');
if (!fs.existsSync(DB_DIR)) fs.mkdirSync(DB_DIR);
const DB_PATH = path.join(DB_DIR, 'cache.db');

let db;
function initDb() {
  db = new Database(DB_PATH);
  // cache table: rawg_id (unique), data (json), fetched_at (unix)
  db.prepare(`
    CREATE TABLE IF NOT EXISTS cache (
      id INTEGER PRIMARY KEY,
      rawg_id INTEGER UNIQUE,
      data TEXT,
      fetched_at INTEGER
    )
  `).run();
}

function getCached(rawg_id) {
  const row = db.prepare('SELECT data, fetched_at FROM cache WHERE rawg_id = ?').get(rawg_id);
  return row ? { data: JSON.parse(row.data), fetched_at: row.fetched_at } : null;
}

function setCached(rawg_id, data) {
  const now = Math.floor(Date.now() / 1000);
  const str = JSON.stringify(data);
  const stmt = db.prepare(`
    INSERT INTO cache (rawg_id, data, fetched_at)
    VALUES (?, ?, ?)
    ON CONFLICT(rawg_id) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at
  `);
  stmt.run(rawg_id, str, now);
}

function getAllCached() {
  return db.prepare('SELECT rawg_id, data, fetched_at FROM cache').all().map(r => ({ rawg_id: r.rawg_id, data: JSON.parse(r.data), fetched_at: r.fetched_at }));
}

module.exports = { initDb, getCached, setCached, getAllCached };
