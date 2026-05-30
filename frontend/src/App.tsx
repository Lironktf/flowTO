import { BeforeAfterPanel } from "./components/BeforeAfterPanel";
import { CopilotPanel } from "./components/CopilotPanel";
import { DebugPanel } from "./components/DebugPanel";
import { FirstRun } from "./components/FirstRun";
import { InterventionDrawer } from "./components/InterventionDrawer";
import { Legend } from "./components/Legend";
import { MapCanvas } from "./components/MapCanvas";
import { PerfStrip } from "./components/PerfStrip";
import { RecomputeOverlay } from "./components/RecomputeOverlay";
import { TimeScrubber } from "./components/TimeScrubber";
import { TopBar } from "./components/TopBar";
import { useAppStore } from "./state/appStore";

export default function App() {
  const phase = useAppStore((s) => s.phase);

  if (phase === "first-run") return <FirstRun />;

  return (
    <>
      <MapCanvas />
      <TopBar />
      <InterventionDrawer />
      <BeforeAfterPanel />
      <CopilotPanel />
      <TimeScrubber />
      <Legend />
      <PerfStrip />
      <RecomputeOverlay />
      <DebugPanel />
    </>
  );
}
