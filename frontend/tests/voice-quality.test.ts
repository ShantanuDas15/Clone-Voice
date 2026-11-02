import { describe, expect, it } from "vitest";

import type { VoiceSample } from "@/lib/api/voice";
import { QUALITY_LABEL, overallQuality } from "@/lib/voice-quality";

const clip = (position: number, rating?: string): VoiceSample => ({
  position,
  agreement: 1,
  mismatch: false,
  quality: rating ? { rating, hints: [] } : null,
});

describe("overallQuality", () => {
  it("is the worst clip's rating, because one bad recording drags the voice down", () => {
    expect(overallQuality([clip(0, "good"), clip(1, "good")])).toBe("good");
    expect(overallQuality([clip(0, "good"), clip(1, "fair")])).toBe("fair");
    expect(overallQuality([clip(0, "fair"), clip(1, "poor"), clip(2, "good")])).toBe("poor");
  });

  it("ignores clips with no or an unknown rating, and is null when none are known", () => {
    expect(overallQuality([clip(0), clip(1, "good")])).toBe("good");
    expect(overallQuality([clip(0, "excellent"), clip(1, "fair")])).toBe("fair");
    expect(overallQuality([clip(0), clip(1)])).toBeNull();
    expect(overallQuality([])).toBeNull();
  });

  it("has wording for every rating", () => {
    expect(QUALITY_LABEL).toEqual({
      good: "Good quality",
      fair: "Fair quality",
      poor: "Poor quality",
    });
  });
});
