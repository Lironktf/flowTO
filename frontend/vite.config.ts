/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  // Two independent HTML entries: the marketing landing (/) and the app (/app.html).
  // Separate module graphs keep the heavy mapbox/deck.gl app out of the landing bundle.
  appType: "mpa",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API + WS to the P06 FastAPI backend during dev.
      // ws:true is required so the /day/stream WebSocket upgrades through the proxy.
      "/api": { target: process.env.VITE_PROXY_TARGET || "http://localhost:8000", changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
