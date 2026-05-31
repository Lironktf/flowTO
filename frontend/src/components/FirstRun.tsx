import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAppStore } from "../state/appStore";

export function FirstRun() {
  const loadTwin = useAppStore((s) => s.loadTwin);
  const loaded = useAppStore((s) => s.loaded);
  const loading = useAppStore((s) => s.loading);
  const error = useAppStore((s) => s.error);
  const [line, setLine] = useState(0);
  // Live edge count from the running backend — reflects whichever graph is
  // loaded (18k OSMnx baseline or the ~88k citywide Centreline), not a hardcode.
  const [edges, setEdges] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then((h) => alive && setEdges(h.edges))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const edgesLabel = edges != null ? edges.toLocaleString() : "…";
  const bootLines = [
    "› booting FlowTO runtime…",
    `› loading Toronto network · ${edgesLabel} edges`,
    "› warming Nemotron-on-device · GB10…",
    "› ready ▸ press “Load the twin”",
  ];

  useEffect(() => {
    if (line >= bootLines.length) return;
    const t = setTimeout(() => setLine((n) => n + 1), line === 0 ? 420 : 760);
    return () => clearTimeout(t);
  }, [line, bootLines.length]);

  return (
    <div id="firstrun" className={loaded ? "hide" : ""}>
      <div className="fr-card">
        <div className="fr-eyebrow">Spark Hack · NVIDIA · local-first</div>
        <h1 className="fr-title">
          A live digital twin of <b>Toronto</b>.
        </h1>
        <div className="fr-lede">
          Two modes: <b>Simulate</b> the matchday on a video-editor timeline, or <b>Edit</b> the
          network top-down — drop closures, lane reductions, one-ways, and signal retiming, and watch
          the twin recompute. 100% on-device.
        </div>
        <div className="fr-meta">
          <div className="m">
            <div className="k">Road edges</div>
            <div className="v">{edgesLabel}</div>
          </div>
          <div className="m">
            <div className="k">Egress demand</div>
            <div className="v">~45,000</div>
          </div>
          <div className="m">
            <div className="k">Blast-radius</div>
            <div className="v">766 ms</div>
          </div>
        </div>
        <button className="btn primary" onClick={() => void loadTwin()} disabled={loading}>
          {loading ? "Loading the real graph…" : "Load the twin"}
        </button>
        {error ? (
          <div className="fr-loadline" style={{ color: "var(--c-sev)" }}>
            {error}
          </div>
        ) : (
          <div className="fr-loadline" dangerouslySetInnerHTML={{ __html: bootLines.slice(0, line + 1).join("&nbsp;&nbsp;") }} />
        )}
      </div>
    </div>
  );
}
