import { DEMO_DEVICE } from "../config";
import { useAppStore } from "../state/appStore";

const SPARK = [5, 7, 6, 9, 8, 11, 9, 12, 10, 13];

export function StatusBar() {
  const edges = useAppStore((s) => s.edges.length);
  const t = useAppStore((s) => s.telemetry);

  return (
    <div id="statusbar">
      <div className="sb-cell">
        <span className="k">Network</span>
        <span className="v">{edges.toLocaleString()} edges</span>
      </div>
      <div className="sb-cell">
        <span className="k">Recompute</span>
        <span className="v">{t.recompute} ms</span>
      </div>
      <div className="sb-cell">
        <span className="k">Subgraph</span>
        <span className="v">{t.subEdges ? t.subEdges.toLocaleString() + " edges" : "—"}</span>
      </div>
      <div className="sb-cell">
        <span className="k">LLM</span>
        <span className="v">{t.llm ? t.llm + " ms" : "—"}</span>
      </div>
      <div className="sb-cell right">
        <span className="k">FPS</span>
        <span className="v good">{t.fps}</span>
        <div className="sb-spark">
          {SPARK.map((h, i) => (
            <i key={i} style={{ height: `${h}px` }} />
          ))}
        </div>
      </div>
      <div className="sb-cell device">
        <span className="k">Compute</span>
        <span className="v cobalt">{DEMO_DEVICE}</span>
      </div>
    </div>
  );
}
