import { describe, expect, it } from "vitest";

import type { VoiceSample } from "@/lib/api/voice";
import { FEW_CLIPS_NUDGE, voiceAdvice } from "@/lib/voice-advice";

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
    expect(voiceAdvice([clip(0), clip(1), clip(2)])).toBeNull();
    expect(voiceAdvice([clip(0, { quality: null }), clip(1), clip(2)])).toBeNull();
  });

  it("names clips that may be another speaker, singular and plural", () => {
    expect(voiceAdvice([clip(0), clip(1, { mismatch: true }), clip(2)])).toBe(
      "Clip 2 may be a different speaker.",
    );
    expect(voiceAdvice([clip(0, { mismatch: true }), clip(1), clip(2, { mismatch: true })])).toBe(
      "Clips 1, 3 may be different speakers.",
    );
  });

  it("reports the worst recording rating, poor over fair", () => {
    const fair = { rating: "fair", hints: [] };
    const poor = { rating: "poor", hints: [] };
    expect(voiceAdvice([clip(0, { quality: fair }), clip(1), clip(2)])).toBe(
      "A recording could be cleaner.",
    );
    expect(voiceAdvice([clip(0, { quality: fair }), clip(1, { quality: poor }), clip(2)])).toBe(
      "A recording is poor.",
    );
  });

  it("joins both concerns", () => {
    expect(
      voiceAdvice([
        clip(0),
        clip(1, { mismatch: true, quality: { rating: "fair", hints: [] } }),
        clip(2),
      ]),
    ).toBe("Clip 2 may be a different speaker. A recording could be cleaner.");
  });

  it("nudges a voice built from one or two clips to add more, and stops at three", () => {
    expect(voiceAdvice([clip(0)])).toBe(FEW_CLIPS_NUDGE);
    expect(voiceAdvice([clip(0), clip(1)])).toBe(FEW_CLIPS_NUDGE);
    expect(voiceAdvice([clip(0), clip(1), clip(2)])).toBeNull();
  });

  it("puts the other concerns before the nudge, and does not nudge a voice with no clip rows", () => {
    expect(voiceAdvice([clip(0, { quality: { rating: "poor", hints: [] } })])).toBe(
      `A recording is poor. ${FEW_CLIPS_NUDGE}`,
    );
    expect(voiceAdvice([])).toBeNull();
  });
});
