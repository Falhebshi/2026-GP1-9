import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // MapLibre ships its own web worker; Vite's pre-bundling breaks it in dev
  optimizeDeps: { exclude: ['maplibre-gl'] },
})
