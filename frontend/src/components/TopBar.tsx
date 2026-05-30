import { Icon } from "./Icons";
import { useAppStore } from "../state/appStore";

export function TopBar() {
  const view = useAppStore((s) => s.view);
  const setView = useAppStore((s) => s.setView);
  const status = useAppStore((s) => s.status);
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const reset = useAppStore((s) => s.reset);
  const showLeft = useAppStore((s) => s.showLeft);
  const showBottom = useAppStore((s) => s.showBottom);
  const showRight = useAppStore((s) => s.showRight);
  const toggleDock = useAppStore((s) => s.toggleDock);

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
        <span className="k">Scenario</span>
        <span className="v">FIFA WC26 — Post-match egress</span>
      </div>

      <div className="tb-right">
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
