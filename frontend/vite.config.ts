import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/output': 'http://localhost:8000',
    },
  },
  build: {
    // Monaco is intentionally isolated as a lazy editor chunk; keep the build
    // warning threshold aligned with that dependency instead of hiding it in
    // the app entry bundle.
    chunkSizeWarningLimit: 3200,
    rollupOptions: {
      output: {
        manualChunks: {
          'cytoscape': ['cytoscape', 'cytoscape-dagre'],
          'monaco-editor': ['monaco-editor'],
        },
      },
    },
  },
})
