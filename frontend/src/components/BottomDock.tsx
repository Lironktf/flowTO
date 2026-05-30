import { useEffect, useMemo, useRef } from "react";
import { TIMELINE } from "../config";
import { congestionSeries } from "../lib/congestion";
import { useAppStore } from "../state/appStore";
import { getArrays } from "../state/tickStore";
import { Icon } from "./Icons";

const SPAN = TIMELINE.endMin - TIMELINE.startMin;
const pct = (min: number) => ((min - TIMELINE.startMin) / SPAN) * 100;
const fmtClock = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(Math.round(min) % 60).padStart(2, "0")}`;

function dateLabel(doy: number): string {
  const d = new Date(Date.UTC(2026, 0, doy));
  return d
    .toLocaleDateString("en-CA", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" })
    .toUpperCase();
}

export function BottomDock() {
  const minute = useAppStore((s) => s.scrubberMinute);
  const setScrubber = useAppStore((s) => s.setScrubber);
  const playing = useAppStore((s) => s.playing);
  const setPlaying = useAppStore((s) => s.setPlaying);
  const speed = useAppStore((s) => s.speed);
  const setSpeed = useAppStore((s) => s.setSpeed);
  const dayOfYear = useAppStore((s) => s.dayOfYear);
  const setDayOfYear = useAppStore((s) => s.setDayOfYear);
  const selectedRoadId = useAppStore((s) => s.selectedRoadId);
  const selectRoad = useAppStore((s) => s.selectRoad);
  const graph = useAppStore((s) => s.graph);
  const pressureSeq = useAppStore((s) => s.pressureSeq);
  const laneRef = useRef<HTMLDivElement>(null);

  // Playback: advance every 520/speed ms, snapped to the step.
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const m = useAppStore.getState().scrubberMinute;
      if (m >= TIMELINE.endMin) {
        setPlaying(false);
        return;
      }
      setScrubber(Math.min(TIMELINE.endMin, m + TIMELINE.step));
    }, 520 / speed);
    return () => clearInterval(id);
  }, [playing, speed, setScrubber, setPlaying]);

  const seekFromClient = (clientX: number) => {
    const el = laneRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    const raw = TIMELINE.startMin + frac * SPAN;
    setScrubber(Math.round(raw / TIMELINE.step) * TIMELINE.step);
  };

  const ticks: { min: number; major: boolean }[] = [];
  for (let m = TIMELINE.startMin; m <= TIMELINE.endMin; m += 60) {
    ticks.push({ min: m, major: m % 180 === 0 });
  }

  // Congestion-over-time: selected road's pressure, else the network average.
  const selSeg = selectedRoadId && graph ? graph.byId.get(selectedRoadId) : null;
  const series = useMemo(() => {
    const arr = getArrays().pressure;
    let amplitude: number;
    if (selSeg) {
      amplitude = Math.max(0.25, arr[selSeg.idx] ?? 0);
    } else {
      let sum = 0;
      let c = 0;
      for (let i = 0; i < arr.length; i++) {
        if (arr[i] > 0) {
          sum += arr[i];
          c++;
        }
      }
      amplitude = Math.max(0.2, c ? sum / c : 0.2);
    }
    return congestionSeries(amplitude, 96, TIMELINE.startMin, TIMELINE.endMin);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selSeg, pressureSeq]);

  const polyline = series
    .map((p) => `${pct(p.min).toFixed(2)},${(100 - p.v * 100).toFixed(2)}`)
    .join(" ");
  const nowV = (() => {
    // value at the current minute (nearest sample)
    let best = series[0];
    for (const p of series) if (Math.abs(p.min - minute) < Math.abs(best.min - minute)) best = p;
    return best?.v ?? 0;
  })();

  return (
    <div className="timeline">
      <div className="tl-bar">
        <div className="tl-transport">
          <button className="tbtn" onClick={() => setScrubber(TIMELINE.startMin)}>
            <Icon.jumpStart />
          </button>
          <button className="tbtn" onClick={() => setScrubber(Math.max(TIMELINE.startMin, minute - TIMELINE.step))}>
            <Icon.stepBack />
          </button>
          <button className="tbtn play" onClick={() => setPlaying(!playing)}>
            {playing ? <Icon.pause /> : <Icon.play />}
          </button>
          <button className="tbtn" onClick={() => setScrubber(Math.min(TIMELINE.endMin, minute + TIMELINE.step))}>
            <Icon.stepFwd />
          </button>
          <button className="tbtn" onClick={() => setScrubber(TIMELINE.endMin)}>
            <Icon.jumpEnd />
          </button>
        </div>

        <div className="tl-clock">
          <span className="t">{fmtClock(minute)}</span>
          <span className="dow">{dateLabel(dayOfYear)}</span>
        </div>

        <div className="day-control">
          <Icon.calendar />
          <input
            type="range"
            className="range-mini"
            min={1}
            max={365}
            value={dayOfYear}
            onChange={(e) => setDayOfYear(Number(e.target.value))}
            title="Day of year"
          />
        </div>

        <div className="tl-right">
          <span className="cong-readout">
            <Icon.chart />
            <span className="cr-tx">
              {selSeg ? selSeg.road_name ?? "Selected road" : "Network"} · {(nowV * 100).toFixed(0)}%
            </span>
            {selSeg && (
              <button className="cr-clear" onClick={() => selectRoad(null)} title="Clear selection">
                ×
              </button>
            )}
          </span>
          <div className="tl-speed">
            {[0.5, 1, 2, 4].map((s) => (
              <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
                {s}×
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="tl-stage">
        <div className="tl-ruler">
          {ticks.map((t) => (
            <div key={t.min} className={`tl-tick ${t.major ? "major" : ""}`} style={{ left: `${pct(t.min)}%` }}>
              {t.major && <span className="tlab">{fmtClock(t.min)}</span>}
            </div>
          ))}
        </div>

        <div className="tl-playzone">
          <svg className="cong-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline
              points={`0,100 ${polyline} 100,100`}
              fill="var(--cobalt-wash)"
              stroke="none"
            />
            <polyline points={polyline} fill="none" stroke="var(--cobalt)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
          </svg>

          <div className="tl-playhead" style={{ left: `${pct(minute)}%` }}>
            <div className="ph-grip" />
            <div className="ph-line" />
          </div>
          <div
            className="tl-scrub"
            ref={laneRef}
            onPointerDown={(e) => {
              (e.target as HTMLElement).setPointerCapture(e.pointerId);
              seekFromClient(e.clientX);
            }}
            onPointerMove={(e) => {
              if (e.buttons === 1) seekFromClient(e.clientX);
            }}
          />
        </div>
      </div>
    </div>
  );
}
