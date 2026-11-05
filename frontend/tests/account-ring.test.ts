import { describe, expect, it } from "vitest";

import { RING_BARS, initialsOf, nameSeed, ringAmplitude } from "@/lib/account-ring";

describe("account ring", () => {
  it("takes initials from the first and last word, in capitals", () => {
    expect(initialsOf("ada lovelace")).toBe("AL");
    expect(initialsOf("  Grace   Brewster  Murray Hopper ")).toBe("GH");
    expect(initialsOf("Plato")).toBe("P");
    expect(initialsOf("   ")).toBe("?");
  });

  it("gives the same name the same ring, and different names different rings", () => {
    expect(nameSeed("Ada")).toBe(nameSeed("Ada"));
    expect(nameSeed("Ada")).not.toBe(nameSeed("Grace"));
    const a = Array.from({ length: RING_BARS }, (_, i) => ringAmplitude(i, nameSeed("Ada")));
    const b = Array.from({ length: RING_BARS }, (_, i) => ringAmplitude(i, nameSeed("Grace")));
    expect(a).not.toEqual(b);
  });

  it("keeps every bar between 0.35 and 1", () => {
    for (let i = 0; i < RING_BARS; i++) {
      const h = ringAmplitude(i, nameSeed("anyone"));
      expect(h).toBeGreaterThanOrEqual(0.35);
      expect(h).toBeLessThanOrEqual(1);
    }
  });
});
