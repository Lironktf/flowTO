import { useEffect, useState } from "react";
import { useAppStore } from "../state/appStore";

const BOOT_LINES = [
  "› loading Toronto Centreline graph … 18,190 edges",
  "› demand model (weather-aware) … ready",
  "› equilibrium engine (BPR + Frank-Wolfe) … ready",
  "› DGX Spark · GB10 · on-device",
];

export function FirstRun() {
  const loadTwin = useAppStore((s) => s.loadTwin);
  const loading = useAppStore((s) => s.loading);
  const error = useAppStore((s) => s.error);
  const [line, setLine] = useState(0);

  useEffect(() => {
    if (line >= BOOT_LINES.length) return;
    const t = setTimeout(() => setLine((n) => n + 1), 420);
    return () => clearTimeout(t);
  }, [line]);

  return (
    <div className="firstrun">
      <div className="eyebrow">Spark Hack · NVIDIA · local-first</div>
      <h1>
        A live digital twin of <span className="to">Toronto</span>.
      </h1>
      <div className="lede">
        Simulate how traffic and transit flow, apply interventions, and watch the network recompute
        in real time — all on-device. The reference scenario is FIFA World Cup 2026 post-match
        egress at BMO Field.
      </div>
      <div className="stats">
        <div>
          <div className="v serif">18,190</div>
          <div className="k">road edges</div>
        </div>
        <div>
          <div className="v serif">~45,000</div>
          <div className="k">egress demand</div>
        </div>
        <div>
          <div className="v serif">&lt;100ms</div>
          <div className="k">blast-radius recompute</div>
        </div>
      </div>
      <button className="btn primary" onClick={() => void loadTwin()} disabled={loading}>
        {loading ? "Loading the real graph…" : "Load the twin"}
      </button>
      {error ? (
        <div className="boot" style={{ color: "var(--bad)" }}>
          {error}
        </div>
      ) : (
        <div className="boot">{BOOT_LINES.slice(0, line).join("  ")}</div>
      )}
    </div>
  );
}
