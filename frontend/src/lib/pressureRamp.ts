/**
 * Congestion ramp — the ONLY place color carries meaning (design/README.md).
 * Linear interpolation between stops; pressure 0 (free) → 1 (gridlock).
 */
export type RGB = [number, number, number];

const STOPS: Array<[number, RGB]> = [
  [0.0, [31, 157, 87]], // free (green)
  [0.35, [138, 175, 31]], // light
  [0.55, [224, 162, 26]], // moderate (amber)
  [0.75, [224, 112, 27]], // heavy (orange)
  [1.0, [210, 58, 50]], // severe (red)
];

function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

/** Remap pressure around the midpoint by `intensity` (default 1.0; range 0.7–1.4). */
export function remapIntensity(p: number, intensity = 1.0): number {
  return clamp01((p - 0.5) * intensity + 0.5);
}

/** Brighten a channel for dark mode: c = min(255, round(c*1.18 + 18)). */
function brighten(c: number): number {
  return Math.min(255, Math.round(c * 1.18 + 18));
}

/** Map a pressure (0–1) to an RGB color along the congestion ramp. */
export function pressureRamp(pressure: number, opts?: { intensity?: number; dark?: boolean }): RGB {
  const p = remapIntensity(clamp01(pressure), opts?.intensity ?? 1.0);
  let lo = STOPS[0];
  let hi = STOPS[STOPS.length - 1];
  for (let i = 0; i < STOPS.length - 1; i++) {
    if (p >= STOPS[i][0] && p <= STOPS[i + 1][0]) {
      lo = STOPS[i];
      hi = STOPS[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const t = (p - lo[0]) / span;
  let rgb: RGB = [
    Math.round(lo[1][0] + (hi[1][0] - lo[1][0]) * t),
    Math.round(lo[1][1] + (hi[1][1] - lo[1][1]) * t),
    Math.round(lo[1][2] + (hi[1][2] - lo[1][2]) * t),
  ];
  if (opts?.dark) rgb = [brighten(rgb[0]), brighten(rgb[1]), brighten(rgb[2])];
  return rgb;
}

export function rgbCss(rgb: RGB): string {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}
