import { Icon } from "./Icons";
import { useAppStore } from "../state/appStore";

export function TopBar() {
  const view = useAppStore((s) => s.view);
  const setView = useAppStore((s) => s.setView);
  const status = useAppStore((s) => s.status);
  const currentName = useAppStore((s) => s.currentName);
  const dirty = useAppStore((s) => s.dirty);
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const reset = useAppStore((s) => s.reset);
  const showLeft = useAppStore((s) => s.showLeft);
  const showBottom = useAppStore((s) => s.showBottom);
  const showRight = useAppStore((s) => s.showRight);
  const toggleDock = useAppStore((s) => s.toggleDock);
  const demandModel = useAppStore((s) => s.demandModel);
  const setDemandModel = useAppStore((s) => s.setDemandModel);
  const runSimulate = useAppStore((s) => s.runSimulate);
  const dayFill = useAppStore((s) => s.dayFill);
  const modelActual = useAppStore((s) => s.modelActual);
  const objects = useAppStore((s) => s.objects);

  // Surface the silent fallback: a real model was requested but the backend
  // served the hand-coded heuristic (xgboost/torch not installed).
  const usingHeuristic = modelActual.toLowerCase().includes("heuristic");

  // No edits → the predicted baseline day (ML, no interventions — instant when
  // precomputed, else progressive). Edits → the ML day-stream is filling; the
  // button reflects how much of the predicted day is ready, and doubles as retry.
  const editing = objects.some((o) => o.visible);
  const dayLive = dayFill.ready >= dayFill.total;
  const runLabel = !editing ? "Baseline" : dayLive ? "Run ▸" : `Computing ${dayFill.ready}/${dayFill.total}`;
  const runIdle = !editing || dayLive;

  return (
    <div id="topbar">
      <div className="brand">
        <span className="mark">
          Flow<b>TO</b>
        </span>
        <span className="sub">Digital Twin · Toronto</span>
      </div>
      <div className="tb-div" />
      <div className="viewseg" role="tablist">
        <button className={view === "sim" ? "on" : ""} onClick={() => setView("sim")} role="tab">
          <Icon.play /> Simulate
        </button>
        <button className={view === "edit" ? "on" : ""} onClick={() => setView("edit")} role="tab">
          <Icon.pencil /> Edit
        </button>
      </div>
      <div className="tb-div" />
      <div className="scenario-tag">
        <span className="k">Simulation</span>
        <span className="v">
          {currentName}
          {dirty ? " •" : ""}
        </span>
      </div>

      <div className="tb-right">
        <div className="viewseg modelseg" role="group" title="Demand model used for the simulation">
          <button
            className={demandModel === "xgboost" ? "on" : ""}
            onClick={() => setDemandModel("xgboost")}
          >
            XGBoost
          </button>
          <button className={demandModel === "gnn" ? "on" : ""} onClick={() => setDemandModel("gnn")}>
            GNN
          </button>
        </div>
        {usingHeuristic && (
          <span className="statuschip" data-state="blocked" title="Requested model not installed; served the fallback heuristic">
            <span className="dot" />⚠ heuristic
          </span>
        )}
        <button
          className={`btn ${runIdle ? "ghost" : "primary"} btn-sm`}
          onClick={() => void runSimulate()}
          title={
            !editing
              ? "Predicted baseline day — scrub and play freely"
              : dayLive
                ? "Predicted day computed — scrub and play freely"
                : `Predicting the day… ${dayFill.ready}/${dayFill.total} hours ready`
          }
        >
          {runLabel}
        </button>
        <div className={`statuschip`} data-state={status.state}>
          <span className="dot" />
          {status.label}
        </div>
        <div className="dock-toggles">
          <button className={`iconbtn ${showLeft ? "on" : ""}`} onClick={() => toggleDock("left")} title="Left dock">
            ▘
          </button>
          <button className={`iconbtn ${showBottom ? "on" : ""}`} onClick={() => toggleDock("bottom")} title="Bottom dock">
            ▂
          </button>
          <button className={`iconbtn ${showRight ? "on" : ""}`} onClick={() => toggleDock("right")} title="Right dock">
            ▝
          </button>
        </div>
        <button className="iconbtn" onClick={() => setTheme(theme === "light" ? "dark" : "light")} title="Theme">
          <Icon.moon />
        </button>
        <button className="btn ghost btn-sm" onClick={() => void reset()}>
          Reset
        </button>
      </div>
    </div>
  );
}
