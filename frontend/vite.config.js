import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // Allow external connections for mobile testing
  },
  build: {
    sourcemap: false,
    minify: 'esbuild', // Use built-in esbuild instead of terser
  }
})