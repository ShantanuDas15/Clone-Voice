import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { STANDARD_ENGINE, engineName } from "@/lib/engine-names";

describe("engineName", () => {
  it.each([
    ["sv2tts", "Standard"],
    ["chatterbox", "Expressive"],
    ["chatterbox_turbo", "Expressive Turbo"],
    ["chatterbox_nano", "Expressive Nano"],
  ])("names %s as %s", (id, name) => {
    expect(engineName(id)).toBe(name);
  });

  it("falls back to a neutral word for an unknown id, never the id", () => {
    expect(engineName("future_engine")).toBe("another");
    expect(engineName("")).toBe("another");
  });

  it("treats sv2tts as the standard engine", () => {
    expect(STANDARD_ENGINE).toBe("sv2tts");
  });
});

describe("engine ids", () => {
  it("every engine the backend can serve has a friendly name", () => {
    const config = readFileSync(path.resolve(__dirname, "../../backend/core/config.py"), "utf8");
    // `TTS_ENGINE: Literal["sv2tts", "chatterbox", ...]`
    const declared = /TTS_ENGINE: Literal\[([^\]]+)\]/.exec(config)?.[1];
    expect(declared).toBeTruthy();
    const ids = [...(declared ?? "").matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1] ?? "");
    expect(ids).toContain("sv2tts");
    for (const id of ids) expect(engineName(id), id).not.toBe("another");
  });
});
