import { useEffect, useRef, useState } from "react";
import { consumeDirty, getTickSeq } from "../state/tickStore";

/** Dev-only FPS / tick counter. Driven by rAF, never by tick data. */
export function DebugPanel() {
  const [fps, setFps] = useState(60);
  const last = useRef(performance.now());
  const frames = useRef(0);

  useEffect(() => {
    let raf = 0;
    const loop = () => {
      // Coalesce tick writes once per frame (the imperative deck update point).
      consumeDirty();
      frames.current++;
      const now = performance.now();
      if (now - last.current >= 1000) {
        setFps(frames.current);
        frames.current = 0;
        last.current = now;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  if (!import.meta.env.DEV) return null;
  return (
    <div
      className="panel"
      style={{ top: 66, left: 340, padding: "6px 10px", zIndex: 40 }}
    >
      <span className="mono" style={{ fontSize: 10 }}>
        {fps} fps · tick {getTickSeq()}
      </span>
    </div>
  );
}
