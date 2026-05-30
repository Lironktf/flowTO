import { timeline } from "../data/demo";
import { useAppStore } from "../state/appStore";

function fmt(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function TimeScrubber() {
  const minute = useAppStore((s) => s.scrubberMinute);
  const setScrubber = useAppStore((s) => s.setScrubber);

  return (
    <div className="panel scrubber">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="mono" style={{ fontSize: 18 }}>
          {fmt(minute)}
        </span>
        <span className="eyebrow">{timeline.dow}</span>
      </div>
      <div className="rail">
        <input
          type="range"
          min={timeline.startMin}
          max={timeline.endMin}
          step={timeline.step}
          value={minute}
          onChange={(e) => setScrubber(Number(e.target.value))}
        />
      </div>
      <div className="mono" style={{ fontSize: 10, color: "var(--ink-3)", display: "flex", justifyContent: "space-between" }}>
        <span>14:00</span>
        <span>kickoff 15:00</span>
        <span>full-time 17:05</span>
        <span>20:00</span>
      </div>
    </div>
  );
}
