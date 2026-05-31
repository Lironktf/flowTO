import { Icon } from "./Icons";
import { SearchBar } from "./SearchBar";
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
      {/* Left zone — caps the rail + left dock */}
      <div className="tb-zone tb-left">
        <div className="brand">
          <span className="mark">
            Flow<b>TO</b>
          </span>
          <span className="sub">Digital Twin · Toronto</span>
        </div>
        <div className="viewseg" role="tablist">
          <button className={view === "sim" ? "on" : ""} onClick={() => setView("sim")} role="tab">
            <Icon.play /> Simulate
          </button>
          <button className={view === "edit" ? "on" : ""} onClick={() => setView("edit")} role="tab">
            <Icon.pencil /> Edit
          </button>
        </div>
      </div>

      {/* Center zone — over the map */}
      <div className="tb-zone tb-center">
        <SearchBar />
      </div>

      {/* Right zone — caps the right dock */}
      <div className="tb-zone tb-right">
        <div className="statuschip" data-state={status.state}>
          <span className="dot" />
          {status.label}
        </div>
        <div className="dock-toggles">
          <button
            className={`iconbtn ${showLeft ? "on" : ""}`}
            onClick={() => toggleDock("left")}
            title="Toggle left panel"
            aria-label="Toggle left panel"
            aria-pressed={showLeft}
          >
            <Icon.panelLeft />
          </button>
          <button
            className={`iconbtn ${showBottom ? "on" : ""}`}
            onClick={() => toggleDock("bottom")}
            title="Toggle bottom panel"
            aria-label="Toggle bottom panel"
            aria-pressed={showBottom}
          >
            <Icon.panelBottom />
          </button>
          <button
            className={`iconbtn ${showRight ? "on" : ""}`}
            onClick={() => toggleDock("right")}
            title="Toggle right panel"
            aria-label="Toggle right panel"
            aria-pressed={showRight}
          >
            <Icon.panelRight />
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
