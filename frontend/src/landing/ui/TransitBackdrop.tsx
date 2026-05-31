/**
 * Dimmed Toronto transit/road backdrop for the hero — signals "transit planner"
 * at a glance. A faint street grid overlaid on the iconic TTC lines (Line 1
 * Yonge-University = yellow U, Line 2 Bloor-Danforth = green E-W, Line 4
 * Sheppard = purple stub), with station ticks + interchange dots.
 * Purely decorative (aria-hidden, pointer-events: none via .hero__transit).
 */

const TTC = { line1: "#f2c500", line2: "#00923f", line4: "#a2308f" };

// Faint, even street grid
const VLINES = Array.from({ length: 1200 / 64 + 1 }, (_, i) => i * 64);
const HLINES = Array.from({ length: 760 / 64 + 1 }, (_, i) => i * 64);

// Station coordinates per line (schematic)
const L2_STATIONS = [120, 250, 360, 490, 620, 780, 910, 1040].map((x) => [x, 250] as const);
const L1_STATIONS = [
  [360, 230], [360, 320], [360, 410], [360, 500], // University/Spadina arm
  [480, 620], [600, 620], [700, 620], // Union curve / bottom
  [780, 500], [780, 410], [780, 320], [780, 230], // Yonge arm
] as const;
const L4_STATIONS = [840, 930, 1010].map((x) => [x, 170] as const);
// Interchanges (where lines cross)
const INTERCHANGES = [
  [360, 250], // St George (L1 ∩ L2)
  [780, 250], // Bloor-Yonge (L1 ∩ L2)
  [780, 170], // Sheppard-Yonge (L1 ∩ L4)
] as const;

export function TransitBackdrop() {
  return (
    <svg
      viewBox="0 0 1200 760"
      preserveAspectRatio="xMidYMid slice"
      role="presentation"
      aria-hidden="true"
    >
      {/* TTC subway lines (drawn first so the road grid overlays on top) */}
      <g className="tb-subway" fill="none" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
        {/* Line 2 — Bloor-Danforth (green, east-west) */}
        <path d="M120 250 H1040" stroke={TTC.line2} />
        {/* Line 1 — Yonge-University-Spadina (yellow U) */}
        <path
          d="M360 200 V560 Q360 620 420 620 H720 Q780 620 780 560 V200"
          stroke={TTC.line1}
        />
        {/* Line 4 — Sheppard (purple stub off the top of the Yonge arm) */}
        <path d="M780 170 H1010" stroke={TTC.line4} />
      </g>

      {/* faint even street grid — overlaid ON TOP of the TTC lines */}
      <g stroke="#ffffff" strokeWidth="1" fill="none" className="tb-roads">
        {VLINES.map((x) => (
          <line key={`v${x}`} x1={x} y1="0" x2={x} y2="760" />
        ))}
        {HLINES.map((y) => (
          <line key={`h${y}`} x1="0" y1={y} x2="1200" y2={y} />
        ))}
      </g>

      {/* station ticks */}
      <g className="tb-stations">
        {L2_STATIONS.map(([x, y], i) => (
          <circle key={`s2${i}`} cx={x} cy={y} r="3.4" fill={TTC.line2} />
        ))}
        {L1_STATIONS.map(([x, y], i) => (
          <circle key={`s1${i}`} cx={x} cy={y} r="3.4" fill={TTC.line1} />
        ))}
        {L4_STATIONS.map(([x, y], i) => (
          <circle key={`s4${i}`} cx={x} cy={y} r="3.4" fill={TTC.line4} />
        ))}
      </g>

      {/* interchange stations */}
      <g className="tb-interchange">
        {INTERCHANGES.map(([x, y], i) => (
          <circle
            key={`i${i}`}
            cx={x}
            cy={y}
            r="6.5"
            fill="#0d0d0d"
            stroke="#ffffff"
            strokeWidth="2.5"
          />
        ))}
      </g>
    </svg>
  );
}
