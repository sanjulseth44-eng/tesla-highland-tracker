import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The site is served from GitHub Pages under /tesla-highland-tracker/.
// Override with VITE_BASE=/ for a root deploy or local static hosting.
export default defineConfig({
  base: process.env.VITE_BASE ?? '/tesla-highland-tracker/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
    // recharts + react in one chunk is ~530 kB minified; fine for a single-page static dashboard.
    chunkSizeWarningLimit: 700,
  },
})
