import { describe, expect, it } from "vitest";
import { clampMinute, fmtClock, minuteToHour, secondsToMinute, timeContext } from "../src/lib/time";

describe("time-of-day conversions", () => {
  it("clamps minute-of-day (never wraps)", () => {
    expect(clampMinute(-5)).toBe(0);
    expect(clampMinute(5000)).toBe(1439);
    expect(clampMinute(1020)).toBe(1020);
  });

  it("formats and converts the clock", () => {
    expect(fmtClock(1020)).toBe("17:00");
    expect(fmtClock(0)).toBe("00:00");
    expect(fmtClock(870)).toBe("14:30");
    expect(minuteToHour(1020)).toBe(17);
    expect(secondsToMinute(14 * 3600)).toBe(14 * 60);
  });
});

describe("timeContext (canonical context sent to the backend)", () => {
  it("derives hour + Mon=0 weekday + month from minute & day-of-year", () => {
    // 2026-06-12 is a Friday → backend weekday 4 (Mon=0), not JS getUTCDay()=5.
    const tc = timeContext(480, 163);
    expect(tc.hour).toBe(8);
    expect(tc.minute).toBe(480);
    expect(tc.month).toBe(6);
    expect(tc.day_of_week).toBe(4); // Friday, Mon=0
    expect(tc.is_weekend).toBe(0);
    expect(tc.day_of_year).toBe(163);
  });

  it("flags weekends with the Mon=0 convention", () => {
    // 2026-06-13 Saturday → day-of-year 164 → weekday 5, is_weekend 1.
    const tc = timeContext(1020, 164);
    expect(tc.day_of_week).toBe(5);
    expect(tc.is_weekend).toBe(1);
  });
});
