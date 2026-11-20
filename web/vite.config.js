import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const web = fileURLToPath(new URL('.', import.meta.url))
const styles = fileURLToPath(new URL('../styles', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // api.py allows this exact origin (CORS). If 5173 were taken, Vite would
    // quietly move to 5174 and every request would be blocked, so fail instead.
    port: 5173,
    strictPort: true,
    // The page imports ../styles/theme.css, the same file the HTML report
    // uses. Vite only serves files inside web/ unless told otherwise.
    fs: { allow: [web, styles] },
  },
})
