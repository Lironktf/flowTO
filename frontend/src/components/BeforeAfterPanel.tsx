import { type MetricKey, metricLabels, metricOrder, metrics } from "../data/demo";
import { useAppStore } from "../state/appStore";

export function BeforeAfterPanel() {
  const networkState = useAppStore((s) => s.networkState);
  const phase = useAppStore((s) => s.phase);

  // Compare reference: surge vs base, mitigated vs surge (design semantics).
  const [from, to, fromLabel, toLabel] =
    networkState === "mit"
      ? (["surge", "mit", "Event", "Mitigated"] as const)
      : (["base", "surge", "Baseline", "Event"] as const);

  if (phase === "baseline" || phase === "first-run") {
    return (
      <div className="panel metrics">
        <div className="eyebrow">Outcome</div>
        <h2 className="panel-title">Before / After</h2>
        <div className="warn-row">Network nominal — apply an intervention or play the matchday.</div>
      </div>
    );
  }

  return (
    <div className="panel metrics">
      <div className="eyebrow">
        {fromLabel} → {toLabel}
      </div>
      <h2 className="panel-title">Before / After</h2>
      <div className="metric-grid">
        {metricOrder.map((k: MetricKey) => {
          const a = metrics[from][k].v;
          const b = metrics[to][k].v;
          const pct = a !== 0 ? ((b - a) / a) * 100 : 0;
          const better = b < a; // lower is better for every metric here
          const arrow = b < a ? "↓" : b > a ? "↑" : "→";
          return (
            <div className="metric" key={k}>
              <div className="label">{metricLabels[k]}</div>
              <div className="val">
                {b.toLocaleString()}
                <span className="mono" style={{ fontSize: 11, marginLeft: 4 }}>
                  {metrics[to][k].u}
                </span>
              </div>
              <div className={`delta ${better ? "good" : "bad"}`}>
                {arrow} {Math.abs(pct).toFixed(0)}% vs {fromLabel.toLowerCase()}
              </div>
            </div>
          );
        })}
      </div>

      {networkState === "surge" ? (
        <div className="warn-row bad">34% local-road infiltration into Parkdale / Liberty Village.</div>
      ) : networkState === "mit" ? (
        <div className="warn-row good">Plan valid. No hard-constraint conflicts.</div>
      ) : null}
    </div>
  );
}
