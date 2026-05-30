import { LOWER_IS_BETTER, METRIC_LABELS, METRIC_ORDER } from "../config";
import { type NetworkState, useAppStore } from "../state/appStore";

function fmt(v: number): string {
  if (Math.abs(v) >= 100) return Math.round(v).toLocaleString();
  return v.toFixed(2);
}

export function BeforeAfterPanel() {
  const networkState = useAppStore((s) => s.networkState);
  const phase = useAppStore((s) => s.phase);
  const summaries = useAppStore((s) => s.summaries);

  if (phase === "baseline" || phase === "first-run") {
    return (
      <div className="panel metrics">
        <div className="eyebrow">Outcome</div>
        <h2 className="panel-title">Before / After</h2>
        <div className="warn-row">
          Network nominal — apply an intervention or play the matchday.
        </div>
      </div>
    );
  }

  // Compare reference: surge vs base, mitigated vs surge (real engine summaries).
  const [from, to, fromLabel, toLabel]: [NetworkState, NetworkState, string, string] =
    networkState === "mit"
      ? ["surge", "mit", "Event", "Mitigated"]
      : ["base", "surge", "Baseline", "Event"];

  const a = summaries[from];
  const b = summaries[to];
  if (!a || !b) {
    return (
      <div className="panel metrics">
        <div className="eyebrow">Outcome</div>
        <h2 className="panel-title">Before / After</h2>
        <div className="warn-row">Computing…</div>
      </div>
    );
  }

  return (
    <div className="panel metrics">
      <div className="eyebrow">
        {fromLabel} → {toLabel} · live engine
      </div>
      <h2 className="panel-title">Before / After</h2>
      <div className="metric-grid">
        {METRIC_ORDER.map((k) => {
          const av = a[k] ?? 0;
          const bv = b[k] ?? 0;
          const pct = av !== 0 ? ((bv - av) / Math.abs(av)) * 100 : 0;
          const lowerBetter = LOWER_IS_BETTER.has(k);
          const better = lowerBetter ? bv <= av : bv >= av;
          const arrow = bv < av ? "↓" : bv > av ? "↑" : "→";
          return (
            <div className="metric" key={k}>
              <div className="label">{METRIC_LABELS[k] ?? k}</div>
              <div className="val">{fmt(bv)}</div>
              <div className={`delta ${better ? "good" : "bad"}`}>
                {arrow} {Math.abs(pct).toFixed(0)}% vs {fromLabel.toLowerCase()}
              </div>
            </div>
          );
        })}
      </div>

      {networkState === "surge" ? (
        <div className="warn-row bad">
          Post-match surge — severe congestion + local-road infiltration near Exhibition.
        </div>
      ) : networkState === "mit" ? (
        <div className="warn-row good">
          Plan applied — congestion eased. No hard-constraint conflicts.
        </div>
      ) : null}
    </div>
  );
}
