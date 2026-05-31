import { useEffect, useState } from "react";
import { useAppStore } from "../state/appStore";

const BOOT_LINES = [
  "› booting FlowTO runtime…",
  "› loading Toronto network · 81,669 edges",
  "› warming baseline assignment · GB10…",
  "› pre-warming blast-radius cache…",
  "› ready ▸ entering the dashboard…",
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

  // The twin auto-boots on app mount (see App.tsx), so this is now a lightweight
  // loading splash that dismisses itself once the graph is ready — no manual gate.
  return (
    <div id="firstrun" className={loaded ? "hide" : ""}>
      <div className="fr-card">
        <div className="fr-eyebrow">Spark Hack · NVIDIA · local-first</div>
        <h1 className="fr-title">
          Loading the <b>Toronto</b> twin…
        </h1>
        {error ? (
          <>
            <div className="fr-loadline" style={{ color: "var(--c-sev)" }}>
              {error}
            </div>
            <button className="btn primary" onClick={() => void loadTwin()} disabled={loading}>
              {loading ? "Retrying…" : "Retry"}
            </button>
          </>
        ) : (
          <div className="fr-loadline" dangerouslySetInnerHTML={{ __html: BOOT_LINES.slice(0, line + 1).join("&nbsp;&nbsp;") }} />
        )}
      </div>
    </div>
  );
}
