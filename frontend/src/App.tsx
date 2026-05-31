import { lazy, Suspense, useEffect } from "react";
import { BottomDock } from "./components/BottomDock";
import { CopilotRegion } from "./components/CopilotPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { FirstRun } from "./components/FirstRun";
import { LeftDock } from "./components/LeftDock";
import { RightDock } from "./components/RightDock";
import { StatusBar } from "./components/StatusBar";
import { ToolRail } from "./components/ToolRail";
import { TopBar } from "./components/TopBar";
import { useAppStore } from "./state/appStore";

// The map pulls in mapbox-gl + deck.gl (~2.7 MB). Load it as its own chunk so the
// app shell paints first (the FirstRun intro covers the brief async load).
const MapCanvas = lazy(() => import("./components/MapCanvas").then((m) => ({ default: m.MapCanvas })));

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
    <ErrorBoundary label="FlowTO">
      <div id="shell">
        <TopBar />
        <div id="rail">
          <ToolRail />
        </div>
        <div id="dock-left" className="dock">
          <LeftDock />
        </div>
        <div id="viewport">
          <Suspense fallback={null}>
            <MapCanvas />
          </Suspense>
        </div>
        <div id="dock-bottom" className="dock">
          <BottomDock />
        </div>
        <div id="dock-right" className="dock">
          <RightDock />
          <ErrorBoundary label="Copilot">
            <CopilotRegion />
          </ErrorBoundary>
        </div>
        <StatusBar />
      </div>
      <FirstRun />
      {/* Tiny-window guard: FlowTO is a desktop ops tool; hidden unless the window is too narrow. */}
      <div id="smallscreen-notice">
        <div className="ssn-card">
          <span className="mark">
            Flow<b>TO</b>
          </span>
          <div className="ssn-t">Best on a larger screen</div>
          <div className="ssn-s">
            FlowTO's live map, timeline, and copilot need a wider viewport. Open it on a desktop or
            widen this window.
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
