import { SCENARIOS, TOOLS } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon, type IconKey } from "./Icons";

const TYPE_COLOR: Record<string, string> = {
  closure: "var(--c-heavy)",
  lane: "var(--c-mod)",
  oneway: "var(--cobalt)",
  signal: "var(--cobalt)",
  surge: "var(--c-sev)",
  transit: "var(--c-free)",
};
const TOOL_ICON: Record<string, IconKey> = {
  closure: "closure",
  lane: "lane",
  oneway: "oneway",
  signal: "signal",
  surge: "surge",
};

export function LeftDock() {
  const activeTool = useAppStore((s) => s.activeTool);
  const selectTool = useAppStore((s) => s.selectTool);
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const selectObject = useAppStore((s) => s.selectObject);
  const toggleObjectVis = useAppStore((s) => s.toggleObjectVis);

  return (
    <>
      {/* Simulate → Scenarios */}
      <section className="region grow v-sim">
        <div className="region-hd">
          <span className="lbl">Scenarios</span>
        </div>
        <div className="region-body">
          <div className="scn">
            {SCENARIOS.map((sc) => (
              <div key={sc.id} className={`scn-item ${sc.active ? "active" : ""}`}>
                <span className="badge">{sc.badge}</span>
                <span className="grow">
                  <div className="nm">{sc.name}</div>
                  <div className="mt">{sc.meta}</div>
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Edit → Interventions */}
      <section className="region v-edit">
        <div className="region-hd">
          <span className="lbl">Interventions</span>
        </div>
        <div className="region-body">
          <div className="tool-list">
            {TOOLS.map((t, i) => {
              const I = Icon[TOOL_ICON[t.id]];
              return (
                <button
                  key={t.id}
                  className={`tool-row ${activeTool === t.id ? "active" : ""}`}
                  onClick={() => selectTool(t.id)}
                >
                  <span className="ti">
                    <I />
                  </span>
                  <span className="tt">
                    <span className="nm">{t.name}</span>
                    <span className="ds">{t.desc}</span>
                  </span>
                  <span className="kbd">{i + 1}</span>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* Edit → Scene outliner */}
      <section className="region grow v-edit">
        <div className="region-hd">
          <span className="lbl">Scene</span>
          <span className="spacer" />
          <span className="meta">{objects.length} obj</span>
        </div>
        <div className="region-body">
          {objects.length === 0 ? (
            <div className="outliner-empty">
              No interventions placed. Pick a tool and click the map to drop one.
            </div>
          ) : (
            <div className="outliner">
              {objects.map((o) => (
                <div
                  key={o.id}
                  className={`out-row ${selectedId === o.id ? "sel" : ""}`}
                  onClick={() => selectObject(o.id)}
                >
                  <span className="od" style={{ background: TYPE_COLOR[o.type] ?? "var(--cobalt)" }} />
                  <span className="on" style={{ opacity: o.visible ? 1 : 0.45 }}>
                    {o.name}
                  </span>
                  <span className="otype">{o.type}</span>
                  <span
                    className="ovis"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleObjectVis(o.id);
                    }}
                  >
                    <Icon.eye />
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
