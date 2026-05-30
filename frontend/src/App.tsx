import { useEffect } from "react";
import { BottomDock } from "./components/BottomDock";
import { CopilotRegion } from "./components/CopilotPanel";
import { FirstRun } from "./components/FirstRun";
import { LeftDock } from "./components/LeftDock";
import { MapCanvas } from "./components/MapCanvas";
import { RightDock } from "./components/RightDock";
import { StatusBar } from "./components/StatusBar";
import { ToolRail } from "./components/ToolRail";
import { TopBar } from "./components/TopBar";
import { useAppStore } from "./state/appStore";

export default function App() {
  const view = useAppStore((s) => s.view);
  const showLeft = useAppStore((s) => s.showLeft);
  const showRight = useAppStore((s) => s.showRight);
  const showBottom = useAppStore((s) => s.showBottom);
  const showRail = useAppStore((s) => s.showRail);

  // Drive the body attributes/classes (CSS does view scoping + dock collapse).
  useEffect(() => {
    document.body.setAttribute("data-view", view);
    document.body.classList.toggle("no-left", !showLeft);
    document.body.classList.toggle("no-right", !showRight);
    document.body.classList.toggle("no-bottom", !showBottom);
    document.body.classList.toggle("no-rail", !showRail);
  }, [view, showLeft, showRight, showBottom, showRail]);

  return (
    <>
      <div id="shell">
        <TopBar />
        <div id="rail">
          <ToolRail />
        </div>
        <div id="dock-left" className="dock">
          <LeftDock />
        </div>
        <div id="viewport">
          <MapCanvas />
        </div>
        <div id="dock-bottom" className="dock">
          <BottomDock />
        </div>
        <div id="dock-right" className="dock">
          <RightDock />
          <CopilotRegion />
        </div>
        <StatusBar />
      </div>
      <FirstRun />
    </>
  );
}
