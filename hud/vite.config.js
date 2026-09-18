import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The bridge (jarvis.bridge) runs on JARVIS_BRIDGE (default 127.0.0.1:8770).
// Vite proxies /api to it so the browser only ever talks to one origin —
// which also matters when the HUD is opened through a tunnelled preview URL.
const bridge = process.env.JARVIS_BRIDGE || 'http://127.0.0.1:8770'
const port = Number(process.env.PORT || 5173)

const proxy = {
  '/api': { target: bridge, changeOrigin: true, ws: false }
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port,
    strictPort: true,
    // allow the e2b/Arena preview host (and any tunnel) to embed the app
    allowedHosts: true,
    proxy,
    hmr: { clientPort: 443, protocol: 'wss' }
  },
  preview: { host: true, port, strictPort: true, allowedHosts: true, proxy },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false }
})
