import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Ollama pulls can take several minutes for larger models.
        // Keep the dev proxy connection open long enough to avoid 504s.
        timeout: 10 * 60 * 1000,
        proxyTimeout: 10 * 60 * 1000,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
