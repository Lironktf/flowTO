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
      // Proxy /api to the FastAPI backend. Target defaults to :8000 but is
      // overridable (e.g. VITE_PROXY_TARGET=http://localhost:8010 when the
      // backend runs on a non-default port, like on the shared Spark).
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
        // ws: forward the WebSocket upgrade too — the day-stream (/api/day/stream,
        // used by "Apply & recompute") is a WS. Without this the upgrade never
        // reaches the backend and the client fails with "Compute failed".
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        landing: resolve(__dirname, "index.html"),
        app: resolve(__dirname, "app.html"),
      },
      output: {
        // Split the heavy map/render libs into their own cacheable vendor chunks
        // so the app shell + first paint aren't blocked by 2.7 MB of mapbox/deck.
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (id.includes("mapbox-gl")) return "mapbox";
          if (id.includes("@deck.gl") || id.includes("@luma.gl") || id.includes("@math.gl")) return "deck";
          if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("/scheduler/")) return "react";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
