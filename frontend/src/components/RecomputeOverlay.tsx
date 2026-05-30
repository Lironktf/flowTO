import { RECOMPUTE_STEPS as recomputeSteps, useAppStore } from "../state/appStore";

export function RecomputeOverlay() {
  const recomputing = useAppStore((s) => s.recomputing);
  const step = useAppStore((s) => s.recomputeStep);
  if (!recomputing) return null;
  const pct = Math.round((step / recomputeSteps.length) * 100);
  return (
    <div className="panel recompute">
      <div className="eyebrow">Recomputing network</div>
      <div className="serif" style={{ fontSize: 16, marginTop: 2 }}>
        {recomputeSteps[Math.min(step, recomputeSteps.length - 1)]}…
      </div>
      <div className="progress">
        <div style={{ width: `${pct}%` }} />
      </div>
      <div className="pips">
        {recomputeSteps.map((s, i) => (
          <div key={s} className={`pip ${i < step ? "on" : ""}`} />
        ))}
      </div>
    </div>
  );
}
