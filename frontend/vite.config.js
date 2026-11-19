import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // MapLibre ships its own web worker; Vite's pre-bundling breaks it in dev
  optimizeDeps: { exclude: ['maplibre-gl'] },
  // The network map server (jaadah/network_congestion/server.py), started with
  // `uvicorn jaadah.network_congestion.server:app --port 8001`: /api/network/days goes to /days
  // The accounts server (backend/accounts/server.py), started with
  // `uvicorn backend.accounts.server:app --port 8003`: /api/auth/login goes
  // to /auth/login and /api/admin/engineers to /admin/engineers. Same
  // address as the website, so its session cookie works.
  server: {
    proxy: {
      '/api/network': {
        target: 'http://localhost:8001',
        rewrite: (path) => path.replace(/^\/api\/network/, ''),
      },
      '/api/auth': {
        target: 'http://localhost:8003',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/api/admin': {
        target: 'http://localhost:8003',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
