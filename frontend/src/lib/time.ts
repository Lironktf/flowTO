/**
 * Canonical time + calendar representation for the frontend — the mirror of the
 * backend's `src/torontosim/timeofday.py`. ONE system so nothing disagrees on
 * units:
 *
 *   - time of day  = minute-of-day, integer 0..1439 (MINUTES_PER_DAY)
 *   - calendar day = day-of-year, 1..365, in a fixed simulated YEAR (2026)
 *
 * Everything the backend needs (hour 0–23, weekday Mon=0..Sun=6, month 1–12,
 * is_weekend) is derived here via `timeContext()`, so the UI only tracks the two
 * canonical values (scrubberMinute + dayOfYear). Keep YEAR and the weekday
 * convention in lock-step with the Python module.
 *
 * NOTE on weekday conventions: JS `Date.getUTCDay()` is Sun=0..Sat=6 (used by the
 * calendar-picker helpers below, which are internally consistent). The BACKEND
 * wants Mon=0..Sun=6, so `timeContext()` converts via `(getUTCDay()+6)%7`.
 */

export const YEAR = 2026;
export const MINUTES_PER_DAY = 1440;
export const SECONDS_PER_DAY = 86_400;

// ---- time of day (minute-of-day) ----

/** Coerce to a valid minute-of-day 0..1439 (clamp, never wrap). */
export const clampMinute = (m: number) =>
  Math.max(0, Math.min(MINUTES_PER_DAY - 1, Math.round(m)));

/** `HH:MM` label for a minute-of-day (e.g. 1020 -> "17:00"). */
export const fmtClock = (m: number) => {
  const x = clampMinute(m);
  return `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}`;
};

/** Hour-of-day 0..23 for a minute-of-day. */
export const minuteToHour = (m: number) => Math.floor(clampMinute(m) / 60);

/** Minute-of-day from a GTFS seconds-of-day value (wraps past midnight). */
export const secondsToMinute = (s: number) => Math.floor(s / 60) % MINUTES_PER_DAY;

// ---- calendar (day-of-year, fixed YEAR) ----

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]; // JS getUTCDay order
export const ORDINALS = ["1st", "2nd", "3rd", "4th", "5th"];

/** Localized date label for a day-of-year, e.g. "FRI 12 JUN". */
export function dateLabel(doy: number): string {
  return new Date(Date.UTC(YEAR, 0, doy))
    .toLocaleDateString("en-CA", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" })
    .toUpperCase();
}

/** Day-of-year -> { month: 0–11 (JS), day: 1–31 }. */
export function dayOfYearToMD(doy: number) {
  const d = new Date(Date.UTC(YEAR, 0, doy));
  return { month: d.getUTCMonth(), day: d.getUTCDate() };
}

/** { month: 0–11 (JS), day } -> day-of-year. */
export function mdToDayOfYear(month: number, day: number) {
  return Math.round((Date.UTC(YEAR, month, day) - Date.UTC(YEAR, 0, 0)) / 86_400_000);
}

export function daysInMonth(month: number) {
  return new Date(Date.UTC(YEAR, month + 1, 0)).getUTCDate(); // YEAR is non-leap
}

/** Day-of-month of the `nth` (1–5) occurrence of `weekday` (0=Sun..6=Sat) in `month`.
 *  Clamps to the last valid occurrence when nth overflows the month. */
export function nthWeekdayOfMonth(month: number, nth: number, weekday: number): number {
  const first = new Date(Date.UTC(YEAR, month, 1)).getUTCDay();
  let dom = 1 + ((weekday - first + 7) % 7) + (nth - 1) * 7;
  const max = daysInMonth(month);
  while (dom > max) dom -= 7;
  return dom;
}

/** Which month / nth-occurrence / weekday (JS Sun=0) a day-of-year lands on. */
export function dayOfYearToParts(doy: number): { month: number; nth: number; weekday: number } {
  const { month, day } = dayOfYearToMD(doy);
  const weekday = new Date(Date.UTC(YEAR, month, day)).getUTCDay();
  const nth = Math.floor((day - 1) / 7) + 1;
  return { month, nth, weekday };
}

// ---- the canonical context the backend consumes ----

export interface TimeContext {
  hour: number; // 0–23
  minute: number; // minute-of-day 0–1439
  day_of_week: number; // Mon=0..Sun=6 (BACKEND convention)
  month: number; // 1–12
  is_weekend: 0 | 1;
  day_of_year: number; // 1–365
  weather: string;
}

/**
 * Build the simulator's time_context from the two canonical UI values. This is
 * the single bridge from "what the UI shows" to "what the sim runs", including
 * the JS(Sun=0) → backend(Mon=0) weekday conversion.
 */
export function timeContext(minute: number, dayOfYear: number, weather = "clear"): TimeContext {
  const d = new Date(Date.UTC(YEAR, 0, dayOfYear));
  const monBased = (d.getUTCDay() + 6) % 7; // JS Sun=0 → Mon=0
  return {
    hour: minuteToHour(minute),
    minute: clampMinute(minute),
    day_of_week: monBased,
    month: d.getUTCMonth() + 1, // 1–12
    is_weekend: monBased >= 5 ? 1 : 0,
    day_of_year: dayOfYear,
    weather,
  };
}
