import { describe, expect, it } from "vitest";

import type { Generation } from "@/lib/api/history";
import { generationDetails } from "@/lib/generation-details";
import { fixtures } from "@/mocks/handlers";

const gen = (over: Partial<Generation> = {}): Generation => ({ ...fixtures.generation, ...over });

describe("generationDetails", () => {
  it("says nothing for a plain or older row", () => {
    expect(generationDetails(gen())).toEqual([]);
    expect(
      generationDetails(
        gen({
          emotion: "auto",
          engine: "sv2tts",
          seed: null,
          emotions_used: [],
          sound_tags_dropped: [],
        }),
      ),
    ).toEqual([]);
  });

  it("names a backup engine", () => {
    expect(
      generationDetails(gen({ engine: "sv2tts", engine_fallback_from: "chatterbox" })),
    ).toEqual(["Made by the backup voice engine (Expressive was unavailable)"]);
  });

  it("names the engine for any row not made by the standard one", () => {
    expect(generationDetails(gen({ engine: "chatterbox" }))).toEqual(["Voice engine: Expressive"]);
    expect(generationDetails(gen({ engine: "chatterbox_nano" }))).toEqual([
      "Voice engine: Expressive Nano",
    ]);
    expect(generationDetails(gen({ engine: "sv2tts" }))).toEqual([]);
  });

  it("never shows an engine id it does not know", () => {
    const facts = generationDetails(gen({ engine: "zonos_v9", engine_fallback_from: "zonos_v8" }));
    expect(facts).toEqual(["Made by the backup voice engine (another was unavailable)"]);
    expect(generationDetails(gen({ engine: "zonos_v9" })).join(" ")).not.toMatch(/zonos/);
  });

  it("says the backup once, not also the engine line", () => {
    expect(
      generationDetails(gen({ engine: "chatterbox_turbo", engine_fallback_from: "chatterbox" })),
    ).toHaveLength(1);
  });

  it("reports the requested delivery and whether it took effect", () => {
    expect(
      generationDetails(gen({ emotion: "happy", intensity: 0.7, style_applied: true })),
    ).toEqual(["Delivery: Happy at 70%"]);
    expect(
      generationDetails(gen({ emotion: "angry", intensity: 1, style_applied: false })),
    ).toEqual(["Delivery: Angry at 100%, not applied by this voice engine"]);
    expect(generationDetails(gen({ emotion: "neutral", intensity: null }))).toEqual([
      "Delivery: Neutral",
    ]);
  });

  it("lists sentence readings, dropped tags and the seed", () => {
    expect(
      generationDetails(
        gen({
          emotions_used: ["neutral", "sad"],
          sound_tags_dropped: ["laugh", "cough"],
          seed: 0,
          seed_applied: false,
        }),
      ),
    ).toEqual([
      "Sentence by sentence: neutral, sad",
      "Left out, not supported by this voice engine: [laugh] [cough]",
      "Seed 0 (not used by this engine)",
    ]);
  });
});
