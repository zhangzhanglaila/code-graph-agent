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
