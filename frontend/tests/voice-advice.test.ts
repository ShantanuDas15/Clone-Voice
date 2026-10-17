import { describe, expect, it } from "vitest";

import type { VoiceSample } from "@/lib/api/voice";
import { voiceAdvice } from "@/lib/voice-advice";

const clip = (position: number, over: Partial<VoiceSample> = {}): VoiceSample => ({
  position,
  agreement: 0.9,
  mismatch: false,
  quality: { rating: "good", hints: [] },
  ...over,
});

describe("voiceAdvice", () => {
  it("is null when nothing needs attention, or nothing is known", () => {
    expect(voiceAdvice([])).toBeNull();
    expect(voiceAdvice([clip(0), clip(1)])).toBeNull();
    expect(voiceAdvice([clip(0, { quality: null })])).toBeNull();
  });

  it("names clips that may be another speaker, singular and plural", () => {
    expect(voiceAdvice([clip(0), clip(1, { mismatch: true })])).toBe(
      "Clip 2 may be a different speaker.",
    );
    expect(voiceAdvice([clip(0, { mismatch: true }), clip(2, { mismatch: true })])).toBe(
      "Clips 1, 3 may be different speakers.",
    );
  });

  it("reports the worst recording rating, poor over fair", () => {
    const fair = { rating: "fair", hints: [] };
    const poor = { rating: "poor", hints: [] };
    expect(voiceAdvice([clip(0, { quality: fair })])).toBe("A recording could be cleaner.");
    expect(voiceAdvice([clip(0, { quality: fair }), clip(1, { quality: poor })])).toBe(
      "A recording is poor.",
    );
  });

  it("joins both concerns", () => {
    expect(
      voiceAdvice([clip(0), clip(1, { mismatch: true, quality: { rating: "fair", hints: [] } })]),
    ).toBe("Clip 2 may be a different speaker. A recording could be cleaner.");
  });
});
