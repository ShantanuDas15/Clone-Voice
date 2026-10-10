import { describe, expect, it } from "vitest";

import { describeRetention } from "@/lib/retention";

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
