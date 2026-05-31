import { TOOLS } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon, type IconKey } from "./Icons";

const TYPE_COLOR: Record<string, string> = {
  closure: "var(--c-sev)",
  surge: "var(--c-heavy)",
};
const TOOL_ICON: Record<string, IconKey> = {
  closure: "closure",
  surge: "surge",
};

/**
 * Restricted-road closure guardrail. Pops in the left menu the moment a closure
 * lands on a "Completely Prohibited" provincial highway (MTO) or a City of
 * Toronto municipal expressway. Dismisses when the offending closure is removed.
 */
function ClosureWarnings() {
  const warnings = useAppStore((s) => s.warnings);
  const restricted = warnings.filter((w) => w.kind === "restricted");
  if (restricted.length === 0) return null;
  return (
    <section className="region v-edit">
      <div className="region-hd">
        <span className="lbl">Restricted road</span>
        <span className="spacer" />
        <span className="meta">{restricted.length}</span>
      </div>
      <div className="region-body">
        {restricted.map((w) => (
          <div key={w.id} className={`warn-row ${w.severity}`}>
            <Icon.warn />
            <div className="wt">
              <b>{w.title}</b>
              <div>{w.detail}</div>
              {w.ref && <span className="wref">{w.ref}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Simulate → Saved simulations (live scenario CRUD). */
function SavedSims() {
  const savedSims = useAppStore((s) => s.savedSims);
  const activeId = useAppStore((s) => s.activeSavedSimId);
  const currentName = useAppStore((s) => s.currentName);
  const dirty = useAppStore((s) => s.dirty);
  const setCurrentName = useAppStore((s) => s.setCurrentName);
  const newSim = useAppStore((s) => s.newSim);
  const saveCurrent = useAppStore((s) => s.saveCurrent);
  const selectSavedSim = useAppStore((s) => s.selectSavedSim);
  const deleteSavedSim = useAppStore((s) => s.deleteSavedSim);

  return (
    <section className="region grow v-sim">
      <div className="region-hd">
        <span className="lbl">Saved simulations</span>
        <span className="spacer" />
        <button className="iconbtn sm" onClick={() => newSim()} title="New simulation">
          <Icon.plus />
        </button>
      </div>
      <div className="region-body">
        <div className="save-row">
          <input
            className="name-input"
            value={currentName}
            onChange={(e) => setCurrentName(e.target.value)}
            placeholder="Simulation name"
          />
          <button className="btn btn-sm primary" onClick={() => void saveCurrent()}>
            <Icon.save /> Save
          </button>
        </div>
        {dirty && <div className="dirty-note">Unsaved changes — Save to {activeId ? "update" : "create"}.</div>}
        <div className="scn">
          {savedSims.length === 0 ? (
            <div className="outliner-empty">
              <span className="ee-ico">
                <Icon.save />
              </span>
              No saved simulations yet. Edit the network, then Save.
            </div>
          ) : (
            savedSims.map((sc) => (
              <div
                key={sc.id}
                className={`scn-item ${activeId === sc.id ? "active" : ""}`}
                onClick={() => void selectSavedSim(sc.id)}
              >
                <span className="badge">SIM</span>
                <span className="grow">
                  <div className="nm">{sc.name ?? sc.id}</div>
                  <div className="mt">{(sc.interventions?.length ?? 0)} interventions</div>
                </span>
                <span
                  className="ovis"
                  title="Delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteSavedSim(sc.id);
                  }}
                >
                  <Icon.trash />
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

/** Edit → edit-type picker + scene outliner. */
function EditPanels() {
  const activeTool = useAppStore((s) => s.activeTool);
  const selectTool = useAppStore((s) => s.selectTool);
  const pending = useAppStore((s) => s.pendingVertices);
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const selectObject = useAppStore((s) => s.selectObject);
  const toggleObjectVis = useAppStore((s) => s.toggleObjectVis);

  return (
    <>
      <section className="region v-edit">
        <div className="region-hd">
          <span className="lbl">Edit type</span>
        </div>
        <div className="region-body">
          <div className="tool-list">
            {TOOLS.map((t) => {
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
                </button>
              );
            })}
          </div>
          {activeTool === "closure" && (
            <div className="dirty-note">
              {pending.length === 0
                ? "Click the first intersection on the map."
                : `Pick the second intersection… (${pending.length}/2)`}
            </div>
          )}
          {activeTool === "surge" && pending.length === 0 && (
            <div className="dirty-note">Click an intersection to inject demand.</div>
          )}
        </div>
      </section>

      <section className="region grow v-edit">
        <div className="region-hd">
          <span className="lbl">Scene</span>
          <span className="spacer" />
          <span className="meta">{objects.length} obj</span>
        </div>
        <div className="region-body">
          {objects.length === 0 ? (
            <div className="outliner-empty">
              <span className="ee-ico">
                <Icon.pin />
              </span>
              No interventions placed. Pick an edit type and click the map.
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

export function LeftDock() {
  return (
    <>
      <ClosureWarnings />
      <SavedSims />
      <EditPanels />
    </>
  );
}
