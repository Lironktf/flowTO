/**
 * Convert the UI's time state (a day-of-year + a minute-of-day) into the
 * backend's `time_context` for the demand models.
 *
 * The two conventions differ and MUST be converted or weekend/rush logic is
 * off-by-one:
 *   - day_of_week: JS `getUTCDay()` is 0=Sun..6=Sat; the backend wants
 *     0=Mon..6=Sun → `(getUTCDay() + 6) % 7`.
 *   - month: JS `getUTCMonth()` is 0-based; the backend wants 1-12 → `+1`.
 * Weather is always "clear" per product requirement.
 *
 * The reference year (2026) matches BottomDock's day-of-year ↔ date mapping.
 */
export interface TimeContext {
  hour: number; // 0-23
  day_of_week: number; // 0=Mon .. 6=Sun
  month: number; // 1-12
  weather: "clear";
}

export function buildTimeContext(dayOfYear: number, scrubberMinute: number): TimeContext {
  const doy = Math.max(1, Math.min(366, Math.round(dayOfYear)));
  const d = new Date(Date.UTC(2026, 0, doy));
  return {
    hour: Math.max(0, Math.min(23, Math.floor(scrubberMinute / 60))),
    day_of_week: (d.getUTCDay() + 6) % 7, // JS 0=Sun..6=Sat → backend 0=Mon..6=Sun
    month: d.getUTCMonth() + 1, // JS 0-based → 1-12
    weather: "clear",
  };
}
