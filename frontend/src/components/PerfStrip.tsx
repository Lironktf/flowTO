import { DEMO_DEVICE } from "../config";
import { useAppStore } from "../state/appStore";

export function PerfStrip() {
  const t = useAppStore((s) => s.telemetry);
  // Recompute latency is the measured /demo/run wall-clock (real number).
  const cells = [
    { k: "Recompute", v: t.recompute ? `${t.recompute} ms` : "—" },
    { k: "LLM latency", v: t.llm ? `${t.llm} ms` : "—" },
    { k: "Frame rate", v: `${t.fps} fps` },
    { k: "Compute", v: DEMO_DEVICE },
  ];
  return (
    <div className="panel perf">
      {cells.map((c) => (
        <div className="cell" key={c.k}>
          <div className="k">{c.k}</div>
          <div className="v">{c.v}</div>
        </div>
      ))}
    </div>
  );
}
