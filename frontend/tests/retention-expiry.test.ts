import { describe, expect, it } from "vitest";

import { expiresSoon } from "@/lib/retention";

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-17T12:00:00Z");
const made = (agoMs: number) => new Date(NOW - agoMs).toISOString();

describe("expiresSoon", () => {
  it("is null without a usable retention period or date", () => {
    for (const days of [null, undefined, 0, -1, Number.NaN]) {
      expect(expiresSoon(made(DAY), days, NOW)).toBeNull();
    }
    expect(expiresSoon("not a date", 30, NOW)).toBeNull();
  });

  it("is null when far from expiry, and when already past it", () => {
    expect(expiresSoon(made(DAY), 30, NOW)).toBeNull(); // 29 days left
    expect(expiresSoon(made(23 * DAY - 1), 30, NOW)).toBeNull(); // just over 7 days left
    expect(expiresSoon(made(30 * DAY), 30, NOW)).toBeNull(); // exactly now
    expect(expiresSoon(made(31 * DAY), 30, NOW)).toBeNull();
  });

  it("counts days, then hours, then says less than an hour", () => {
    expect(expiresSoon(made(23 * DAY), 30, NOW)).toBe("7 days");
    expect(expiresSoon(made(28.5 * DAY), 30, NOW)).toBe("1 day");
    expect(expiresSoon(made(29.5 * DAY), 30, NOW)).toBe("12 hours");
    expect(expiresSoon(made(29 * DAY + 23 * 3_600_000), 30, NOW)).toBe("1 hour");
    expect(expiresSoon(made(30 * DAY - 10 * 60_000), 30, NOW)).toBe("less than an hour");
  });

  it("works for a retention shorter than the notice window", () => {
    expect(expiresSoon(made(0), 1, NOW)).toBe("1 day"); // exactly one day left
    expect(expiresSoon(made(DAY / 2), 1, NOW)).toBe("12 hours");
  });
});
