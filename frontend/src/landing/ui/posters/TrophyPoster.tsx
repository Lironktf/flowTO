/**
 * FIFA trophy fallback (mobile / reduced-motion / Suspense). Owned by the
 * Trophy agent — currently a placeholder ellipse silhouette to be replaced
 * with a trophy (goblet/globe-on-base) silhouette in gold.
 */
export function TrophyPoster() {
  return (
    <div
      className="stage-fill"
      style={{ display: "grid", placeItems: "center", position: "relative" }}
      aria-hidden="true"
    >
      <div className="glow" style={{ width: "70%", height: "70%", inset: "15%" }} />
      <svg
        viewBox="0 0 200 320"
        width="44%"
        style={{ position: "relative", maxHeight: "88%" }}
        role="img"
        aria-label="FIFA World Cup trophy"
      >
        <defs>
          <linearGradient id="st" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ffe9a8" />
            <stop offset="0.5" stopColor="#d4af37" />
            <stop offset="1" stopColor="#8a6a1f" />
          </linearGradient>
        </defs>
        <g
          fill="none"
          stroke="url(#st)"
          strokeWidth="3"
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity="0.92"
        >
          {/* Globe on top */}
          <circle cx="100" cy="56" r="30" />
          <path d="M71 56 H129 M100 26 V86" />
          {/* Two figures curving down and inward into the stem */}
          <path d="M80 84 C68 124 82 172 100 196" />
          <path d="M120 84 C132 124 118 172 100 196" />
          {/* Bowl flaring from the stem (connected to the body) */}
          <path d="M80 196 C80 218 120 218 120 196" />
          {/* Plinth + base, connected (no gap) */}
          <path d="M76 218 H124 L132 250 H68 Z" />
          <path d="M62 250 H138 V266 H62 Z" />
        </g>
      </svg>
    </div>
  );
}
