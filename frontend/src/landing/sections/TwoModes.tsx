import { useEffect, useRef, type ReactNode } from "react";
import { Badge } from "../ui/Badge";
import { Reveal } from "../ui/Reveal";

function ModeCard({
  tag,
  title,
  body,
  widget,
}: {
  tag: string;
  title: string;
  body: string;
  widget: ReactNode;
}) {
  return (
    <div className="card">
      <div className="mode-card__head">
        <span className="mode-card__tag">{tag}</span>
      </div>
      <h3 className="h3">{title}</h3>
      <p className="engine-card__body" style={{ marginTop: 12 }}>
        {body}
      </p>
      <div className="mode-card__widget">{widget}</div>
    </div>
  );
}

/** Mini NLE timeline mock (unchanged). */
function SimWidget() {
  return (
    <svg
      className="sim-svg"
      viewBox="0 0 360 180"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid slice"
      role="img"
    >
      <title>Non-linear timeline scrubbing a matchday simulation</title>
      <defs>
        <linearGradient id="heat" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#bdff02" />
          <stop offset="0.5" stopColor="#e0a21a" />
          <stop offset="1" stopColor="#d23a32" />
        </linearGradient>
      </defs>
      {/* transport */}
      <circle className="sim-play" cx="26" cy="30" r="9" fill="none" stroke="#d0ff00" strokeWidth="2" />
      <path className="sim-play" d="M23 26 L31 30 L23 34 Z" fill="#d0ff00" />
      <rect x="50" y="26" width="280" height="8" rx="4" fill="#262626" />
      {/* ruler ticks */}
      {Array.from({ length: 12 }).map((_, i) => (
        <rect key={i} x={30 + i * 28} y="52" width="1.5" height="8" fill="#3a3a3a" />
      ))}
      {/* heat track */}
      <rect className="sim-heat" x="30" y="74" width="300" height="16" rx="5" fill="url(#heat)" opacity="0.9" />
      {/* demand clip */}
      <rect className="sim-demand" x="210" y="102" width="84" height="16" rx="5" fill="#d23a32" opacity="0.75" />
      <rect x="30" y="102" width="150" height="16" rx="5" fill="#262626" />
      {/* plan track */}
      <rect x="30" y="130" width="300" height="16" rx="5" fill="#161616" stroke="#262626" />
      {/* playhead */}
      <g className="sim-playhead">
        <rect x="206" y="20" width="2" height="138" fill="#6f9bff" />
        <circle cx="207" cy="20" r="4" fill="#6f9bff" />
      </g>
    </svg>
  );
}

/* ============================================================================
   EditWidget — a top-down road-closure choreography on a 3×3 grid.

   Cycle (~12s, looping):
     1. cars flow normally across the grid (incl. the middle road)
     2. cars fade out
     3. a closure is placed on the mid-left + mid-right intersections and the
        middle road segment between them fades to red
     4. cars respawn from the corners and reroute AROUND the closed road
   rAF-driven (mutates SVG attrs directly — no per-frame React render),
   IntersectionObserver-gated, and static under prefers-reduced-motion.
   ============================================================================ */

type Pt = { x: number; y: number };

const COLS = [60, 180, 300];
const ROWS = [36, 90, 144];
const N = (c: number, r: number): Pt => ({ x: COLS[c], y: ROWS[r] });

// Named intersections
const TL = N(0, 0), TC = N(1, 0), TR = N(2, 0);
const ML = N(0, 1), C = N(1, 1), MR = N(2, 1);
const BL = N(0, 2), BC = N(1, 2), BR = N(2, 2);

const NODES: Pt[] = [TL, TC, TR, ML, C, MR, BL, BC, BR];

const CYCLE = 12; // seconds

interface Car {
  phase: "normal" | "reroute";
  route: Pt[];
  period: number; // seconds per loop of the route
  offset: number; // 0..1 phase offset along the route
}

const CARS: Car[] = [
  // Normal flow — note two cars use the middle road that later closes.
  { phase: "normal", route: [ML, C, MR], period: 3.2, offset: 0.0 },
  { phase: "normal", route: [MR, C, ML], period: 3.2, offset: 0.45 },
  { phase: "normal", route: [TL, TC, TR], period: 3.6, offset: 0.2 },
  { phase: "normal", route: [BR, BC, BL], period: 3.6, offset: 0.6 },
  // Reroute — enter from corners, go AROUND the closed middle segment.
  { phase: "reroute", route: [TL, TC, TR, MR], period: 3.8, offset: 0.0 },
  { phase: "reroute", route: [BR, BC, BL, ML], period: 3.8, offset: 0.4 },
  { phase: "reroute", route: [TR, MR, BR, BC, BL], period: 4.6, offset: 0.7 },
];

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function pointAlong(route: Pt[], u: number): Pt {
  const segs: number[] = [];
  let total = 0;
  for (let i = 0; i < route.length - 1; i++) {
    const d = Math.hypot(route[i + 1].x - route[i].x, route[i + 1].y - route[i].y);
    segs.push(d);
    total += d;
  }
  let d = clamp01(u) * total;
  for (let i = 0; i < segs.length; i++) {
    if (d <= segs[i] || i === segs.length - 1) {
      const f = segs[i] === 0 ? 0 : d / segs[i];
      return { x: lerp(route[i].x, route[i + 1].x, f), y: lerp(route[i].y, route[i + 1].y, f) };
    }
    d -= segs[i];
  }
  return route[route.length - 1];
}

function lerpColor(a: string, b: string, t: number): string {
  const pa = [parseInt(a.slice(1, 3), 16), parseInt(a.slice(3, 5), 16), parseInt(a.slice(5, 7), 16)];
  const pb = [parseInt(b.slice(1, 3), 16), parseInt(b.slice(3, 5), 16), parseInt(b.slice(5, 7), 16)];
  const c = pa.map((v, i) => Math.round(lerp(v, pb[i], clamp01(t))));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

const ROAD_GREY = "#2c2c2c";
const CLOSED_RED = "#d23a32";

// Phase windows (seconds within the cycle)
function carOpacity(car: Car, t: number): number {
  if (car.phase === "normal") {
    if (t < 3.3) return 1;
    if (t < 4.3) return 1 - (t - 3.3) / 1.0;
    return 0;
  }
  if (t < 6.5) return 0;
  if (t < 7.1) return (t - 6.5) / 0.6;
  if (t < 11.3) return 1;
  if (t < 11.9) return 1 - (t - 11.3) / 0.6;
  return 0;
}
function carU(car: Car, t: number): number {
  const base = car.phase === "normal" ? t : Math.max(0, t - 6.5);
  return (base / car.period + car.offset) % 1;
}
function markerLevel(t: number): number {
  if (t < 4.5) return 0;
  if (t < 5.1) return (t - 4.5) / 0.6;
  if (t < 11.8) return 1;
  if (t < 12) return 1 - (t - 11.8) / 0.2;
  return 0;
}
function redness(t: number): number {
  if (t < 5.0) return 0;
  if (t < 6.0) return (t - 5.0) / 1.0;
  if (t < 11.8) return 1;
  if (t < 12) return 1 - (t - 11.8) / 0.2;
  return 0;
}

function EditWidget() {
  const svgRef = useRef<SVGSVGElement>(null);
  const carRefs = useRef<(SVGCircleElement | null)[]>([]);
  const mlRef = useRef<SVGGElement>(null);
  const mrRef = useRef<SVGGElement>(null);
  const midRef = useRef<SVGLineElement>(null);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const apply = (t: number) => {
      CARS.forEach((car, i) => {
        const el = carRefs.current[i];
        if (!el) return;
        const o = carOpacity(car, t);
        el.style.opacity = String(o);
        if (o > 0.001) {
          const p = pointAlong(car.route, carU(car, t));
          el.setAttribute("cx", p.x.toFixed(1));
          el.setAttribute("cy", p.y.toFixed(1));
        }
      });
      const m = markerLevel(t);
      [mlRef.current, mrRef.current].forEach((g) => {
        if (!g) return;
        g.style.opacity = String(clamp01(m));
        g.style.transform = `scale(${(0.5 + 0.5 * clamp01(m)).toFixed(3)})`;
      });
      if (midRef.current) {
        midRef.current.setAttribute("stroke", lerpColor(ROAD_GREY, CLOSED_RED, redness(t)));
      }
    };

    if (reduced) {
      // Static end-state: closure placed, road closed, a couple cars on a reroute path.
      apply(8.5);
      return;
    }

    let raf = 0;
    let running = false;
    let startTs = 0;
    const frame = (ts: number) => {
      if (!startTs) startTs = ts;
      apply(((ts - startTs) / 1000) % CYCLE);
      raf = requestAnimationFrame(frame);
    };
    const start = () => {
      if (running) return;
      running = true;
      startTs = 0;
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    const io = new IntersectionObserver(
      (entries) => (entries[0]?.isIntersecting ? start() : stop()),
      { threshold: 0.15 },
    );
    if (svgRef.current) io.observe(svgRef.current);
    return () => {
      io.disconnect();
      stop();
    };
  }, []);

  const ring = (p: Pt, ref: React.Ref<SVGGElement>) => (
    <g ref={ref} className="edit-closure" style={{ transform: "scale(0.5)", opacity: 0 }}>
      <circle cx={p.x} cy={p.y} r="13" fill="rgba(210,58,50,0.12)" stroke={CLOSED_RED} strokeWidth="2.5" />
      <path
        d={`M${p.x - 6} ${p.y - 6} L${p.x + 6} ${p.y + 6} M${p.x + 6} ${p.y - 6} L${p.x - 6} ${p.y + 6}`}
        stroke={CLOSED_RED}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </g>
  );

  return (
    <svg
      ref={svgRef}
      className="edit-svg"
      viewBox="0 0 360 180"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid slice"
      role="img"
    >
      <title>Placing a road closure and watching traffic reroute around it</title>
      {/* static roads (all but the middle horizontal, which is dynamic) */}
      <g stroke={ROAD_GREY} strokeWidth="6" fill="none" strokeLinecap="round">
        <path d="M60 36 H300" />
        <path d="M60 144 H300" />
        <path d="M60 36 V144" />
        <path d="M180 36 V144" />
        <path d="M300 36 V144" />
      </g>
      {/* dynamic middle road — recolours grey → red when closed */}
      <line ref={midRef} x1="60" y1="90" x2="300" y2="90" stroke={ROAD_GREY} strokeWidth="6" strokeLinecap="round" />
      {/* intersection dots */}
      <g fill="#454545">
        {NODES.map((n, i) => (
          <circle key={i} cx={n.x} cy={n.y} r="3.6" />
        ))}
      </g>
      {/* closure markers (mid-left + mid-right) */}
      {ring(ML, mlRef)}
      {ring(MR, mrRef)}
      {/* cars */}
      {CARS.map((_, i) => (
        <circle
          key={i}
          ref={(el) => {
            carRefs.current[i] = el;
          }}
          r="4.6"
          fill="#6f9bff"
          opacity="0"
          style={{ filter: "drop-shadow(0 0 3px rgba(111,155,255,0.7))" }}
        />
      ))}
    </svg>
  );
}

export function TwoModes() {
  return (
    <section className="section" id="modes">
      <div className="container">
        <div className="sec-head sec-head--center">
          <Badge>One model of the city, two ways to use it</Badge>
          <h2 className="h2">One model of the city. Two ways to use it.</h2>
        </div>
        <Reveal>
          <div className="grid-2">
            <ModeCard
              tag="Simulate"
              title="Play the day forward."
              body="Watch traffic build through rush hour or a big event like a film, and compare how the city looks before and after your plan — side by side."
              widget={<SimWidget />}
            />
            <ModeCard
              tag="Edit"
              title="Plan right on the map."
              body="Close a street, add a transit route, change a turn or retime a light — and see the knock-on effects across the city immediately."
              widget={<EditWidget />}
            />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
