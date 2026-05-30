export function Legend() {
  return (
    <div className="panel legend">
      <div className="eyebrow" style={{ marginBottom: 4 }}>
        Edge pressure
      </div>
      <div
        className="rail"
        style={{ width: 220, margin: 0 }}
        aria-label="free flow to gridlock"
      />
      <div
        className="mono"
        style={{ fontSize: 9, color: "var(--ink-3)", display: "flex", justifyContent: "space-between", marginTop: 2 }}
      >
        <span>free</span>
        <span>gridlock</span>
      </div>
    </div>
  );
}
