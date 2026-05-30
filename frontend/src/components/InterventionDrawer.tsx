import { scenarios, tools } from "../data/demo";
import { useAppStore } from "../state/appStore";

export function InterventionDrawer() {
  const activeTool = useAppStore((s) => s.activeTool);
  const setTool = useAppStore((s) => s.setTool);
  const previewVisible = useAppStore((s) => s.previewVisible);
  const showPreview = useAppStore((s) => s.showPreview);
  const applyPlan = useAppStore((s) => s.applyPlan);
  const discardPreview = useAppStore((s) => s.discardPreview);
  const fireSurge = useAppStore((s) => s.fireSurge);
  const eventFired = useAppStore((s) => s.eventFired);

  return (
    <div className="panel left">
      <div className="eyebrow">Workspace</div>
      <h2 className="panel-title">Interventions</h2>
      <div className="tool-grid">
        {tools.map((t) => (
          <div
            key={t.id}
            className={`tool ${activeTool === t.id ? "active" : ""}`}
            onClick={() => {
              setTool(t.id);
              if (!eventFired) fireSurge();
              showPreview();
            }}
          >
            <div className="n">{t.name}</div>
            <div className="d">{t.desc}</div>
          </div>
        ))}
      </div>

      {previewVisible && (
        <div className="warn-row" style={{ marginTop: 14 }}>
          <div className="eyebrow">Recommended plan</div>
          <ol style={{ margin: "6px 0 8px", paddingLeft: 18, fontSize: 12 }}>
            <li>Eastbound contraflow on Lake Shore Blvd W (Strachan → Bathurst)</li>
            <li>Retime Dufferin &amp; Strachan signals — 110 s egress splits</li>
            <li>Close Princes' Blvd; hold 509 / 511 transit priority</li>
          </ol>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary" onClick={applyPlan}>
              Apply &amp; recompute
            </button>
            <button className="btn" onClick={discardPreview}>
              Discard
            </button>
          </div>
        </div>
      )}

      <div className="eyebrow" style={{ marginTop: 16 }}>
        Scenarios
      </div>
      {scenarios.map((sc) => (
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
