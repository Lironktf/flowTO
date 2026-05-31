import { useEffect, useMemo, useRef, useState } from "react";
import { TIMELINE } from "../config";
import { describeSegment } from "../api/graph";
import { congestionSeries } from "../lib/congestion";
import { describeSegmentAsync } from "../lib/mapboxCrossStreet";
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

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function dayOfYearToMD(doy: number) {
  const d = new Date(Date.UTC(2026, 0, doy));
  return { month: d.getUTCMonth(), day: d.getUTCDate() };
}
function mdToDayOfYear(month: number, day: number) {
  return Math.round((Date.UTC(2026, month, day) - Date.UTC(2026, 0, 0)) / 86400000);
}
function daysInMonth(month: number) {
  return new Date(Date.UTC(2026, month + 1, 0)).getUTCDate(); // 2026 non-leap
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const ORDINALS = ["1st", "2nd", "3rd", "4th", "5th"];

// Day-of-month of the `nth` (1-5) occurrence of `weekday` (0=Sun..6=Sat) in `month`.
// Clamps to the last valid occurrence when the nth overflows the month.
function nthWeekdayOfMonth(month: number, nth: number, weekday: number): number {
  const first = new Date(Date.UTC(2026, month, 1)).getUTCDay();
  let dom = 1 + ((weekday - first + 7) % 7) + (nth - 1) * 7;
  const max = daysInMonth(month);
  while (dom > max) dom -= 7;
  return dom;
}

// Inverse: which month / nth-occurrence / weekday a dayOfYear lands on.
function dayOfYearToParts(doy: number): { month: number; nth: number; weekday: number } {
  const { month, day } = dayOfYearToMD(doy);
  const weekday = new Date(Date.UTC(2026, month, day)).getUTCDay();
  const nth = Math.floor((day - 1) / 7) + 1;
  return { month, nth, weekday };
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

  // Descriptive readout for the selected segment (instant label, upgraded async).
  const [segLabel, setSegLabel] = useState<string>("");
  useEffect(() => {
    if (!selSeg || !graph || !selectedRoadId) {
      setSegLabel("");
      return;
    }
    let alive = true;
    setSegLabel(describeSegment(graph, selectedRoadId).label);
    describeSegmentAsync(graph, selectedRoadId)
      .then((d) => {
        if (alive) setSegLabel(d.label);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRoadId, graph, pressureSeq]);

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
          {(() => {
            const { month, nth, weekday } = dayOfYearToParts(dayOfYear);
            const apply = (m: number, n: number, w: number) =>
              setDayOfYear(mdToDayOfYear(m, nthWeekdayOfMonth(m, n, w)));
            return (
              <>
                <select
                  className="date-select"
                  value={month}
                  title="Month"
                  onChange={(e) => apply(Number(e.target.value), nth, weekday)}
                >
                  {MONTHS.map((label, i) => (
                    <option key={i} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
                <select
                  className="date-select"
                  value={nth}
                  title="Week of month"
                  onChange={(e) => apply(month, Number(e.target.value), weekday)}
                >
                  {ORDINALS.map((label, i) => (
                    <option key={i} value={i + 1}>
                      {label}
                    </option>
                  ))}
                </select>
                <select
                  className="date-select"
                  value={weekday}
                  title="Day of week"
                  onChange={(e) => apply(month, nth, Number(e.target.value))}
                >
                  {WEEKDAYS.map((label, i) => (
                    <option key={i} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
              </>
            );
          })()}
        </div>

        <div className="tl-right">
          <span
            className="cong-readout"
            title={
              selSeg
                ? "Congestion on the selected road at this time of day"
                : "Network-wide congestion at this time of day"
            }
          >
            <Icon.chart />
            <span className="cr-tx">
              {selSeg ? segLabel || selSeg.road_name || "Selected road" : "Network"} · {(nowV * 100).toFixed(0)}%
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
            <div
              className="ph-grip"
              onPointerDown={(e) => {
                (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
                seekFromClient(e.clientX);
              }}
              onPointerMove={(e) => {
                if (e.buttons === 1) seekFromClient(e.clientX);
              }}
            />
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
