import { SCENARIOS, TOOLS } from "../config";
import { useAppStore } from "../state/appStore";

export function InterventionDrawer() {
  const phase = useAppStore((s) => s.phase);
  const networkState = useAppStore((s) => s.networkState);
  const fireSurge = useAppStore((s) => s.fireSurge);
  const applyPlan = useAppStore((s) => s.applyPlan);

  const showPlan = networkState === "surge" && phase === "surge";

  return (
    <div className="panel left">
      <div className="eyebrow">Workspace</div>
      <h2 className="panel-title">Interventions</h2>
      <div className="tool-grid">
        {TOOLS.map((t) => (
          <div
            key={t.id}
            className="tool"
            onClick={() => {
              // Model the event first (real surge run) so a fix can be applied.
              if (networkState === "base") void fireSurge();
            }}
          >
            <div className="n">{t.name}</div>
            <div className="d">{t.desc}</div>
          </div>
        ))}
      </div>

      {showPlan && (
        <div className="warn-row" style={{ marginTop: 14 }}>
          <div className="eyebrow">Recommended plan</div>
          <ol style={{ margin: "6px 0 8px", paddingLeft: 18, fontSize: 12 }}>
            <li>Eastbound contraflow on Lake Shore Blvd W (Strachan → Bathurst)</li>
            <li>Retime Dufferin &amp; Strachan signals — 110 s egress splits</li>
            <li>Close Princes' Blvd; hold 509 / 511 transit priority</li>
          </ol>
          <button className="btn primary" onClick={() => void applyPlan()}>
            Apply &amp; recompute
          </button>
        </div>
      )}

      <div className="eyebrow" style={{ marginTop: 16 }}>
        Scenarios
      </div>
      {SCENARIOS.map((sc) => (
        <div key={sc.id} className="tool" style={{ marginTop: 8 }}>
          <div className="n">
            <span className="chip" style={{ marginRight: 6 }}>
              {sc.badge}
            </span>
            {sc.name}
          </div>
          <div className="d">{sc.meta}</div>
        </div>
      ))}
    </div>
  );
}
