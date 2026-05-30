import { perf } from "../data/demo";
import { useAppStore } from "../state/appStore";

export function PerfStrip() {
  const t = useAppStore((s) => s.telemetry);
  const cells = [
    { k: "Recompute", v: `${t.recompute} ms` },
    { k: "Affected subgraph", v: `${t.subEdges.toLocaleString()} edges` },
    { k: "LLM latency", v: t.llm ? `${t.llm} ms` : "—" },
    { k: "Frame rate", v: `${t.fps} fps` },
    { k: "Compute", v: perf.device },
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
