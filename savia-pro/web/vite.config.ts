import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the Python service, so the browser only ever
// talks to one origin and no CORS preflight is needed while developing.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 43951,
    proxy: { "/api": { target: "http://127.0.0.1:43950", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
