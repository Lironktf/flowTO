import { LOWER_IS_BETTER, METRIC_LABELS, METRIC_ORDER } from "../config";
import { type Modelled, useAppStore } from "../state/appStore";
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
  transit: "transit",
};

function fmt(v: number): string {
  return Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(2);
}

function BeforeAfter() {
  const modelled = useAppStore((s) => s.modelled);
  const compare = useAppStore((s) => s.compare);
  const setCompare = useAppStore((s) => s.setCompare);
  const summaries = useAppStore((s) => s.summaries);

  if (modelled === "base") {
    return (
      <section className="region grow v-sim">
        <div className="region-hd">
          <span className="lbl">Before / After</span>
        </div>
        <div className="region-body">
          <div className="metrics-empty">
            <div className="big">Network nominal</div>
            <div className="sm">Scrub to full-time or ask the Copilot to model the egress surge.</div>
          </div>
        </div>
      </section>
    );
  }

  const [from, to, fromLabel, toLabel]: [Modelled, Modelled, string, string] =
    modelled === "mit" ? ["surge", "mit", "Event", "Mitigated"] : ["base", "surge", "Baseline", "Event"];
  const a = summaries[from] ?? {};
  const b = summaries[to] ?? {};
  const hero = "average_pressure";
  const heroA = a[hero] ?? 0;
  const heroB = b[hero] ?? 0;
  const heroMax = Math.max(heroA, heroB, 0.001);

  return (
    <section className="region grow v-sim">
      <div className="region-hd">
        <span className="lbl">Before / After</span>
        <span className="spacer" />
        <div className="ba-toggle">
          <button className={compare === "before" ? "on" : ""} onClick={() => setCompare("before")}>
            {fromLabel}
          </button>
          <button className={compare === "after" ? "on" : ""} onClick={() => setCompare("after")}>
            {toLabel}
          </button>
        </div>
      </div>
      <div className="region-body">
        <div className="metrics-grid">
          <div className="metric wide">
            <div className="lab">
              <span>{METRIC_LABELS[hero]}</span>
              <span>
                {fromLabel} → {toLabel}
              </span>
            </div>
            <div className="val">
              {fmt(heroB)}
              <span className="u">avg</span>
            </div>
            <div className="barpair">
              <div className="barrow">
                <span className="bl">{fromLabel}</span>
                <div className="bartrack">
                  <div className="barfill" style={{ width: `${(heroA / heroMax) * 100}%`, background: "var(--ink-3)" }} />
                </div>
                <span className="bv">{fmt(heroA)}</span>
              </div>
              <div className="barrow">
                <span className="bl">{toLabel}</span>
                <div className="bartrack">
                  <div
                    className="barfill"
                    style={{ width: `${(heroB / heroMax) * 100}%`, background: heroB <= heroA ? "var(--c-free)" : "var(--c-sev)" }}
                  />
                </div>
                <span className="bv">{fmt(heroB)}</span>
              </div>
            </div>
          </div>

          {METRIC_ORDER.filter((k) => k !== hero).map((k) => {
            const av = a[k] ?? 0;
            const bv = b[k] ?? 0;
            const pct = av !== 0 ? ((bv - av) / Math.abs(av)) * 100 : 0;
            const lower = LOWER_IS_BETTER.has(k);
            const cls = bv === av ? "flat" : (lower ? bv < av : bv > av) ? "good" : "bad";
            const arrow = bv < av ? "↓" : bv > av ? "↑" : "→";
            return (
              <div className="metric" key={k}>
                <div className="lab">{METRIC_LABELS[k] ?? k}</div>
                <div className="val">{fmt(bv)}</div>
                <div className={`delta ${cls}`}>
                  {arrow} {Math.abs(pct).toFixed(0)}%
                </div>
              </div>
            );
          })}
        </div>

        {modelled === "surge" ? (
          <div className="warn-row">
            <Icon.warn />
            <div className="wt">
              <b>Cut-through risk</b> — egress spills onto Parkdale / Liberty Village local streets.
            </div>
          </div>
        ) : (
          <div className="warn-row ok">
            <Icon.check />
            <div className="wt">
              <b>Plan valid.</b> No hard-constraint conflicts; congestion eased vs the unmitigated event.
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Inspector() {
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const deleteObject = useAppStore((s) => s.deleteObject);
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
            <div className="sm">Pick a tool from the rail and click the map to place an intervention, or select one from the Scene.</div>
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
              <span className="pk">Location</span>
              <span className="pv mono">
                {sel.coord[1].toFixed(4)}, {sel.coord[0].toFixed(4)}
              </span>
            </div>
            <div className="prop">
              <span className="pk">Edge</span>
              <span className="pv mono">{sel.edge_id ?? "—"}</span>
            </div>
            <div className="prop">
              <span className="pk">Status</span>
              <span className="pv">Applied · recomputed</span>
            </div>
            <div className="insp-actions">
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
      <BeforeAfter />
      <Inspector />
    </>
  );
}
