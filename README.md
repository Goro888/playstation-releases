# Full-Stack PlayStation Releases App

Overview
- Backend: server/ (Express + SQLite caching, talks to RAWG.io)
- Frontend: client/ (React + Vite)

Prereqs
- Node 18+
- (optional) RAWG API key to avoid rate limits: https://rawg.io/apidocs

Setup
1. Clone / copy this project.
2. Setup server env:
   - cd server
   - cp .env.example .env
   - (optional) edit .env and set RAWG_API_KEY
   - npm install
   - npm run dev
3. Setup client:
   - cd client
   - cp .env.example .env
   - (optional) set VITE_API_BASE if your backend runs on a different URL
   - npm install
   - npm run dev

Server runs on http://localhost:4000 by default.
Client runs on http://localhost:5173 by default.

Notes
- The server caches RAWG responses for 24 hours in SQLite (data/cache.db).
- Favorites are stored in browser localStorage.
