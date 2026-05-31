import { useEffect, useState } from "react";
import { useAppStore } from "../state/appStore";

const BOOT_LINES = [
  "› booting FlowTO runtime…",
  "› loading Toronto network · 81,669 edges",
  "› warming baseline assignment · GB10…",
  "› ready ▸ press “Load the twin”",
];

export function FirstRun() {
  const loadTwin = useAppStore((s) => s.loadTwin);
  const loaded = useAppStore((s) => s.loaded);
  const loading = useAppStore((s) => s.loading);
  const error = useAppStore((s) => s.error);
  const [line, setLine] = useState(0);

  useEffect(() => {
    if (line >= BOOT_LINES.length) return;
    const t = setTimeout(() => setLine((n) => n + 1), line === 0 ? 420 : 760);
    return () => clearTimeout(t);
  }, [line]);

  return (
    <div id="firstrun" className={loaded ? "hide" : ""}>
      <div className="fr-card">
        <div className="fr-eyebrow">Spark Hack · NVIDIA · local-first</div>
        <h1 className="fr-title">
          A live digital twin of <b>Toronto</b>.
        </h1>
        <div className="fr-lede">
          Two modes: <b>Simulate</b> the day on a timeline with time-of-day lighting, or <b>Edit</b>{" "}
          the network top-down — seal a corridor between two intersections or inject a demand surge,
          and watch the twin recompute. 100% on-device.
        </div>
        <div className="fr-meta">
          <div className="m">
            <div className="k">Road edges</div>
            <div className="v">81,669</div>
          </div>
          <div className="m">
            <div className="k">Egress demand</div>
            <div className="v">~45,000</div>
          </div>
          <div className="m">
            <div className="k">Blast-radius</div>
            <div className="v">7.47 s</div>
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
          <div className="fr-loadline" dangerouslySetInnerHTML={{ __html: BOOT_LINES.slice(0, line + 1).join("&nbsp;&nbsp;") }} />
        )}
      </div>
    </div>
  );
}
