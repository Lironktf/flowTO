import { useEffect, useState } from "react";
import { useAppStore, type SceneObject } from "../state/appStore";
import { Icon, type IconKey } from "./Icons";

const TYPE_COLOR: Record<string, string> = {
  closure: "var(--c-sev)",
  surge: "var(--c-heavy)",
};
const TOOL_ICON: Record<string, IconKey> = {
  closure: "closure",
  surge: "surge",
};
const SEV_ICON: Record<string, IconKey> = {
  danger: "warn",
  warn: "warn",
  info: "check",
};

/** Warnings list (bylaw conflicts + risk bands from live pressures). */
function WarningsBody() {
  const warnings = useAppStore((s) => s.warnings);
  if (warnings.length === 0)
    return (
      <div className="insp-empty">
        <div className="big">All clear</div>
        <div className="sm">No bylaw conflicts or risk flags for the current model.</div>
      </div>
    );
  return (
    <>
      {warnings.map((w) => {
        const I = Icon[SEV_ICON[w.severity] ?? "info"];
        return (
          <div key={w.id} className={`warn-row ${w.severity}`}>
            <I />
            <div className="wt">
              <b>{w.title}</b>
              <div>{w.detail}</div>
              {w.ref && <span className="wref">{w.ref}</span>}
            </div>
          </div>
        );
      })}
    </>
  );
}

/** Read-only summary of a selected object — the Inspector's view-mode twin. */
function ObjectDetails({ sel }: { sel: SceneObject | undefined }) {
  if (!sel)
    return (
      <div className="insp-empty">
        <div className="big">Nothing selected</div>
        <div className="sm">Click an intervention pin on the map to see its details.</div>
      </div>
    );
  const dirs =
    sel.surge &&
    ((["n", "e", "s", "w"] as const).filter((d) => sel.surge!.dirs[d]).map((d) => d.toUpperCase()).join(" / ") || "—");
  return (
    <>
      <div className="insp-head">
        <span className="ih-ico" style={{ background: TYPE_COLOR[sel.type] ?? "var(--cobalt)" }}>
          {(() => {
            const I = Icon[TOOL_ICON[sel.type] ?? "closure"];
            return <I />;
          })()}
        </span>
        <div className="ih-tx">
          <div className="a">{sel.name}</div>
          <div className="b">{sel.type}</div>
        </div>
      </div>

      <div className="prop">
        <span className="pk">Street</span>
        <span className="pv">{sel.roadName ?? "—"}</span>
      </div>
      <div className="prop">
        <span className="pk">Location</span>
        <span className="pv mono">
          {sel.coord[1].toFixed(4)}, {sel.coord[0].toFixed(4)}
        </span>
      </div>
      {sel.type === "closure" ? (
        <div className="prop">
          <span className="pk">Sealed edges</span>
          <span className="pv mono">{sel.edgeIds?.length ?? 0}</span>
        </div>
      ) : (
        <div className="prop">
          <span className="pk">Typical</span>
          <span className="pv mono">
            {sel.baselinePressure != null ? `${sel.baselinePressure.toFixed(2)} pressure` : "—"}
          </span>
        </div>
      )}

      {sel.type === "surge" && sel.surge && (
        <>
          <div className="section-label mt">Demand change</div>
          <div className="prop">
            <span className="pk">Kind</span>
            <span className="pv">{sel.surge.kind === "relief" ? "Relief" : "Surge"}</span>
          </div>
          <div className="prop">
            <span className="pk">Directions</span>
            <span className="pv">{dirs}</span>
          </div>
          <div className="prop">
            <span className="pk">{sel.surge.mode === "relative" ? "Percent" : "Vehicles"}</span>
            <span className="pv mono">
              {sel.surge.mode === "relative" ? `${sel.surge.amount}%` : `${sel.surge.amount}/hour`}
            </span>
          </div>
          <div className="hint">
            {(() => {
              const verb = sel.surge.kind === "relief" ? "Remove" : "Add";
              const along = sel.roadName ? ` along ${sel.roadName}` : "";
              return sel.surge.mode === "absolute"
                ? `${verb} ${sel.surge.amount} vehicles/hour${along} toward ${dirs}.`
                : `${sel.surge.kind === "relief" ? "Reduce" : "Increase"} demand${along} by ${sel.surge.amount}% toward ${dirs}.`;
            })()}
          </div>
        </>
      )}
    </>
  );
}

/** Simulate → Warnings ⇄ Details (read-only). Selecting a pin opens Details. */
function SimPanel() {
  const warnings = useAppStore((s) => s.warnings);
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const sel = objects.find((o) => o.id === selectedId);
  const [tab, setTab] = useState<"warnings" | "details">("warnings");
  // Selecting an object opens Details; deselecting returns to Warnings.
  useEffect(() => setTab(selectedId ? "details" : "warnings"), [selectedId]);

  return (
    <section className="region grow v-sim">
      <div className="region-hd">
        <span className="tabset">
          <button className={tab === "warnings" ? "on" : ""} onClick={() => setTab("warnings")}>
            Warnings
          </button>
          <button className={tab === "details" ? "on" : ""} onClick={() => setTab("details")}>
            Details
          </button>
        </span>
        <span className="spacer" />
        {tab === "warnings" && <span className="meta">{warnings.length}</span>}
      </div>
      <div className="region-body">{tab === "warnings" ? <WarningsBody /> : <ObjectDetails sel={sel} />}</div>
    </section>
  );
}

/** Edit → Inspector (editable fields per intervention type). */
function Inspector() {
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const deleteObject = useAppStore((s) => s.deleteObject);
  const setSurgeParams = useAppStore((s) => s.setSurgeParams);
  const applyEdits = useAppStore((s) => s.applyEdits);
  const sel = objects.find((o) => o.id === selectedId);

  return (
    <section className="region grow v-edit">
      <div className="region-hd">
        <span className="lbl">Inspector</span>
      </div>
      <div className="region-body">
        {!sel ? (
          <div className="insp-empty">
            <div className="big">Nothing selected</div>
            <div className="sm">Pick an edit type from the rail and click the map, or select an object from the Scene.</div>
          </div>
        ) : (
          <>
            <div className="insp-head">
              <span className="ih-ico" style={{ background: TYPE_COLOR[sel.type] ?? "var(--cobalt)" }}>
                {(() => {
                  const I = Icon[TOOL_ICON[sel.type] ?? "closure"];
                  return <I />;
                })()}
              </span>
              <div className="ih-tx">
                <div className="a">{sel.name}</div>
                <div className="b">{sel.type}</div>
              </div>
            </div>

            <div className="prop">
              <span className="pk">Street</span>
              <span className="pv">{sel.roadName ?? "—"}</span>
            </div>
            <div className="prop">
              <span className="pk">Location</span>
              <span className="pv mono">
                {sel.coord[1].toFixed(4)}, {sel.coord[0].toFixed(4)}
              </span>
            </div>
            {sel.type === "closure" ? (
              <div className="prop">
                <span className="pk">Sealed edges</span>
                <span className="pv mono">{sel.edgeIds?.length ?? 0}</span>
              </div>
            ) : (
              <div className="prop">
                <span className="pk">Typical</span>
                <span className="pv mono">
                  {sel.baselinePressure != null ? `${sel.baselinePressure.toFixed(2)} pressure` : "—"}
                </span>
              </div>
            )}

            {sel.type === "surge" && sel.surge && (
              <>
                <div className="section-label mt">Demand change</div>
                <div className="prop">
                  <span className="pk">Kind</span>
                  <span className="pv">
                    <span className="seg-mini">
                      <button
                        className={sel.surge.kind === "surge" ? "on" : ""}
                        onClick={() => setSurgeParams(sel.id, { kind: "surge" })}
                      >
                        Surge
                      </button>
                      <button
                        className={sel.surge.kind === "relief" ? "on" : ""}
                        onClick={() => setSurgeParams(sel.id, { kind: "relief" })}
                      >
                        Relief
                      </button>
                    </span>
                  </span>
                </div>
                <div className="prop">
                  <span className="pk">Directions</span>
                  <span className="pv">
                    <span className="seg-mini">
                      {(["n", "e", "s", "w"] as const).map((d) => (
                        <button
                          key={d}
                          className={sel.surge!.dirs[d] ? "on" : ""}
                          onClick={() =>
                            setSurgeParams(sel.id, { dirs: { ...sel.surge!.dirs, [d]: !sel.surge!.dirs[d] } })
                          }
                        >
                          {d.toUpperCase()}
                        </button>
                      ))}
                    </span>
                  </span>
                </div>
                <div className="prop">
                  <span className="pk">{sel.surge.mode === "relative" ? "Percent" : "Vehicles"}</span>
                  <span className="pv">
                    <span className="field">
                      <input
                        type="number"
                        value={sel.surge.amount}
                        min={0}
                        step={sel.surge.mode === "relative" ? 5 : 50}
                        onChange={(e) => setSurgeParams(sel.id, { amount: Number(e.target.value) })}
                      />
                    </span>
                  </span>
                </div>
                <div className="prop">
                  <span className="pk">Mode</span>
                  <span className="pv">
                    <span className="seg-mini">
                      <button
                        className={sel.surge.mode === "absolute" ? "on" : ""}
                        onClick={() => setSurgeParams(sel.id, { mode: "absolute" })}
                      >
                        Absolute
                      </button>
                      <button
                        className={sel.surge.mode === "relative" ? "on" : ""}
                        onClick={() => setSurgeParams(sel.id, { mode: "relative" })}
                      >
                        Relative %
                      </button>
                    </span>
                  </span>
                </div>
                <div className="hint">
                  {(() => {
                    const verb = sel.surge.kind === "relief" ? "Remove" : "Add";
                    const along = sel.roadName ? ` along ${sel.roadName}` : "";
                    const dirs =
                      (["n", "e", "s", "w"] as const).filter((d) => sel.surge!.dirs[d]).map((d) => d.toUpperCase()).join("/") || "—";
                    return sel.surge.mode === "absolute"
                      ? `${verb} ${sel.surge.amount} vehicles/hour${along} toward ${dirs}.`
                      : `${sel.surge.kind === "relief" ? "Reduce" : "Increase"} demand${along} by ${sel.surge.amount}% toward ${dirs}.`;
                  })()}
                </div>
              </>
            )}

            <div className="insp-actions">
              <button className="btn btn-sm primary" onClick={() => void applyEdits()}>
                Apply &amp; recompute
              </button>
              <button className="btn btn-sm" onClick={() => deleteObject(sel.id)}>
                Delete
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function RightDock() {
  return (
    <>
      <SimPanel />
      <Inspector />
    </>
  );
}
