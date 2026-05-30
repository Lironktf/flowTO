import { useAppStore } from "../state/appStore";

const STATUS: Record<string, { cls: string; label: string }> = {
  baseline: { cls: "", label: "Baseline · nominal" },
  recomputing: { cls: "cobalt", label: "Recomputing…" },
  surge: { cls: "bad", label: "Post-match surge · gridlock" },
  mitigated: { cls: "", label: "Mitigated · plan applied" },
  blocked: { cls: "warn", label: "Action blocked · bylaw conflict" },
  "first-run": { cls: "", label: "Idle" },
};

export function TopBar() {
  const phase = useAppStore((s) => s.phase);
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const reset = useAppStore((s) => s.reset);
  const showTransit = useAppStore((s) => s.showTransit);
  const toggleTransit = useAppStore((s) => s.toggleTransit);
  const status = STATUS[phase] ?? STATUS.baseline;

  return (
    <div className="topbar">
      <div className="wordmark">
        Flow<span className="to">TO</span>
      </div>
      <div className="sub">Digital Twin · Toronto</div>
      <div className="chip">FIFA WC26 — Post-match egress</div>
      <div className="spacer" />
      <div className={`chip ${status.cls}`}>
        <span className="dot" />
        {status.label}
      </div>
      <button className={`btn ${showTransit ? "primary" : ""}`} onClick={toggleTransit}>
        Transit
      </button>
      <button className="btn" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
        {theme === "light" ? "Dark" : "Light"}
      </button>
      <button className="btn" onClick={() => void reset()}>
        Reset
      </button>
    </div>
  );
}
