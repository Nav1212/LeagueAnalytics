import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: vite on :5173 proxies /api to the TypeScript server on :8000.
// Prod: `vite build` -> dist/, served directly by the server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
