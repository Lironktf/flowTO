/**
 * Congestion-over-time helpers for the Simulation bottom bar.
 *
 * We don't yet have a per-edge time series from the backend (flagged as a
 * dependency in the plan), so we shape a plausible diurnal curve from the
 * current pressure `amplitude` (the selected road's pressure, or the network
 * average). When a real series endpoint lands, replace `congestionSeries` with
 * the fetched values — the chart consumes the same `{min, v}[]` shape.
 */

/** Diurnal demand factor (0–1) with AM (~08:00) and PM (~17:30) peaks. */
export function diurnalFactor(min: number): number {
  const am = Math.exp(-(((min - 480) / 110) ** 2));
  const pm = Math.exp(-(((min - 1050) / 130) ** 2));
  const base = 0.14;
  return Math.min(1, base + 0.86 * Math.max(am, pm * 1.04));
}

export interface CongestionPoint {
  min: number;
  v: number;
}

/** Sample the congestion curve across a day, scaled by `amplitude` (0–1+). */
export function congestionSeries(
  amplitude: number,
  n = 96,
  startMin = 0,
  endMin = 24 * 60,
): CongestionPoint[] {
  const out: CongestionPoint[] = [];
  const amp = Math.max(0.05, amplitude);
  for (let i = 0; i < n; i++) {
    const min = startMin + ((endMin - startMin) * i) / (n - 1);
    out.push({ min, v: Math.min(1, amp * diurnalFactor(min)) });
  }
  return out;
}
