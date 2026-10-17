import { describe, expect, it } from "vitest";

import { describeLinkLifetime, describeRetention } from "@/lib/retention";

describe("describeRetention", () => {
  it.each([
    [30, "30 days"],
    [1, "1 day"],
    [1.4, "1 day"],
    [2.5, "3 days"],
    [0.5, "12 hours"],
    [0.01, "1 hour"],
    [1 / 24, "1 hour"],
  ])("%s -> %s", (days, text) => expect(describeRetention(days)).toBe(text));

  it.each([0, -1, NaN, Infinity, null, undefined, "30" as unknown as number])(
    "gives no figure for %s",
    (value) => expect(describeRetention(value)).toBeNull(),
  );
});

describe("describeLinkLifetime", () => {
  it.each([
    [30, "30 minutes"],
    [1, "1 minute"],
    [45.4, "45 minutes"],
    [60, "1 hour"],
    [120, "2 hours"],
    [90, "90 minutes"],
    [0, null],
    [-5, null],
    [Number.NaN, null],
    [null, null],
    [undefined, null],
  ])("%s -> %s", (minutes, text) => expect(describeLinkLifetime(minutes)).toBe(text));
});
