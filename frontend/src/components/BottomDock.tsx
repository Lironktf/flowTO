import { useEffect, useRef } from "react";
import { TIMELINE } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon } from "./Icons";

const SPAN = TIMELINE.endMin - TIMELINE.startMin;
const pct = (min: number) => ((min - TIMELINE.startMin) / SPAN) * 100;
const fmtClock = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;

export function BottomDock() {
  const minute = useAppStore((s) => s.scrubberMinute);
  const setScrubber = useAppStore((s) => s.setScrubber);
  const playing = useAppStore((s) => s.playing);
  const setPlaying = useAppStore((s) => s.setPlaying);
  const speed = useAppStore((s) => s.speed);
  const setSpeed = useAppStore((s) => s.setSpeed);
  const modelled = useAppStore((s) => s.modelled);
  const laneRef = useRef<HTMLDivElement>(null);

  // Playback: advance every 520/speed ms, snapped to the 15-min step.
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

  // Ruler ticks every 15 min; major + label on the hour.
  const ticks: { min: number; major: boolean }[] = [];
  for (let m = TIMELINE.startMin; m <= TIMELINE.endMin; m += TIMELINE.step) {
    ticks.push({ min: m, major: m % 60 === 0 });
  }
  const frame = Math.round((minute - TIMELINE.startMin) * 2);

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
            <Icon.play />
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
          <span className="frame">f {frame}</span>
          <span className="dow">{TIMELINE.dow}</span>
        </div>
        <div className="tl-right">
          <span className="dow">{minute >= TIMELINE.fulltime ? "Full-time · egress" : "Matchday replay"}</span>
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

        <div className="tl-kfrow">
          <div className="tl-kf filled" style={{ left: `${pct(TIMELINE.kickoff)}%` }} onClick={() => setScrubber(TIMELINE.kickoff)} title="Kickoff" />
          <div className="tl-kf event" style={{ left: `${pct(TIMELINE.fulltime)}%` }} onClick={() => setScrubber(TIMELINE.fulltime)} title="Full-time" />
        </div>

        <div className="tl-playzone">
          <div className="tl-tracks">
            <div className="tl-track">
              <span className="trk-name">Congest</span>
              <div className="trk-lane">
                <div className="trk-fill">
                  <div
                    className="heat"
                    style={{
                      background:
                        "linear-gradient(90deg, var(--c-free), var(--c-light) 45%, var(--c-mod) 62%, var(--c-sev) 78%, var(--c-heavy))",
                    }}
                  />
                </div>
              </div>
            </div>
            <div className="tl-track">
              <span className="trk-name">Demand</span>
              <div className="trk-lane">
                <div className="trk-clip" style={{ left: `${pct(TIMELINE.kickoff)}%`, width: `${pct(TIMELINE.fulltime) - pct(TIMELINE.kickoff)}%` }}>
                  <span className="cl">MATCH 90'</span>
                </div>
                <div className="trk-clip evt" style={{ left: `${pct(TIMELINE.fulltime)}%`, width: "16%" }}>
                  <span className="cl">EGRESS 45k</span>
                </div>
              </div>
            </div>
            <div className="tl-track">
              <span className="trk-name">Plan</span>
              <div className="trk-lane">
                {modelled === "mit" ? (
                  <div className="trk-clip transit" style={{ left: `${pct(TIMELINE.fulltime)}%`, width: "26%" }}>
                    <span className="cl">CONTRAFLOW + 509/511</span>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

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
