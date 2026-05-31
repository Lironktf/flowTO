/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// API proxy target — overridable so multiple branch instances can each point at
// their own backend (e.g. VITE_API_TARGET=http://localhost:8001).
const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  // Two independent HTML entries: the marketing landing (/) and the app (/app.html).
  // Separate module graphs keep the heavy mapbox/deck.gl app out of the landing bundle.
  appType: "mpa",
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        landing: resolve(__dirname, "index.html"),
        app: resolve(__dirname, "app.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API + WS to the FastAPI backend during dev (target is env-overridable).
      "/api": { target: apiTarget, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
