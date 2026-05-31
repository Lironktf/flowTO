/**
 * CN Tower fallback (mobile / reduced-motion / Suspense). Stylized silhouette +
 * lime glow; no bitmap, no network. Owned by the Hero agent.
 */
export function TowerPoster() {
  return (
    <div
      className="stage-fill"
      style={{
        display: "grid",
        placeItems: "start center",
        position: "relative",
        paddingTop: "4%",
      }}
      aria-hidden="true"
    >
      <div className="glow" style={{ width: "70%", height: "70%", inset: "8%" }} />
      <svg
        viewBox="0 0 120 320"
        width="44%"
        style={{ position: "relative", maxHeight: "82%" }}
        role="img"
        aria-label="CN Tower"
      >
        <defs>
          <linearGradient id="tw" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#bdff02" stopOpacity="0.9" />
            <stop offset="1" stopColor="#3a3f24" stopOpacity="0.5" />
          </linearGradient>
        </defs>
        <g fill="none" stroke="url(#tw)" strokeWidth="2">
          <path d="M57 300 L60 70 M63 300 L60 70" />
          <ellipse cx="60" cy="92" rx="20" ry="9" />
          <path d="M48 92 L48 112 Q60 122 72 112 L72 92" />
          <path d="M60 70 L60 14" />
          <circle cx="60" cy="12" r="2.4" fill="#d0ff00" stroke="none" />
          <path d="M44 300 L60 250 L76 300" />
        </g>
      </svg>
    </div>
  );
}
