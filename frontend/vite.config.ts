import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Die Corporate-Design-Assets liegen außerhalb von frontend/, weil sie auch die
// PDF-Erzeugung im Backend braucht (ab Phase 3). Der Alias und server.fs.allow
// machen sie für Vite erreichbar – ohne fs.allow scheitert nur der
// Entwicklungsserver, der Build läuft weiter. Der Fehler fällt also erst beim
// nächsten `npm run dev` auf.
const cdVerzeichnis = fileURLToPath(new URL('../assets/cd', import.meta.url))
const projektwurzel = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@cd': cdVerzeichnis,
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: [projektwurzel],
    },
    proxy: {
      // Der Umweg über den Vite-Server ist keine Bequemlichkeit, sondern Voraussetzung
      // der Sitzungsführung: nur so sind Oberfläche und API dieselbe Herkunft, und das
      // Sitzungs-Cookie mit SameSite=Lax wird mitgeschickt. Ohne Proxy bräuchte es
      // SameSite=None samt CORS – also eine schwächere Einstellung nur für die Entwicklung.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Assets mit Namenshash, damit der Browser sie dauerhaft behalten darf. Die index.html
    // wird vom Backend mit no-store ausgeliefert (siehe app/auslieferung.py).
    assetsInlineLimit: 4096,
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
    // design/ enthält die Vorlagen-Mockups samt support.js – dort gibt es keine Tests.
    exclude: ['node_modules', 'dist', '../design/**'],
  },
})
