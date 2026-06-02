import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/flowto.css";

// FAKE backend: when VITE_MOCK=1, shim fetch/WebSocket so the whole demo runs
// in-browser off the committed graph — no server, no Spark, no Nemotron. Must
// install before <App/> mounts (it auto-calls loadTwin on mount).
if (import.meta.env.VITE_MOCK) {
  const { installMockBackend } = await import("./mock/install");
  installMockBackend();
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
