import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4317, strictPort: true,
    watch: { ignored: ['**/.local/**', '**/.reference/**', '**/test-results/**', '**/playwright-report/**'] },
    proxy: { '/api/avatar': { target: 'http://127.0.0.1:4318', ws: true, changeOrigin: true }, '/savia': 'http://127.0.0.1:4318' },
  },
  build: {
    target: 'es2022',
    rollupOptions: { output: { manualChunks: { three: ['three'] } } },
  },
});
