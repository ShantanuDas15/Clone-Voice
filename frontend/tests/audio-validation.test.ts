import { describe, expect, it } from "vitest";

import {
  MAX_AUDIO_BYTES,
  baseMediaType,
  canonicalAudioFile,
  canonicalMediaType,
  validateAudioFile,
} from "@/lib/validation/audio";

const f = (name: string, type: string, size = 1000) => ({ name, type, size });

describe("validateAudioFile", () => {
  it("accepts WAV, MP3 and WEBM, including parameterised MIME types", () => {
    expect(validateAudioFile(f("a.wav", "audio/wav"))).toBeNull();
    expect(validateAudioFile(f("a.wav", "audio/x-wav"))).toBeNull();
    expect(validateAudioFile(f("a.mp3", "audio/mpeg"))).toBeNull();
    expect(validateAudioFile(f("rec.webm", "audio/webm;codecs=opus"))).toBeNull();
  });
  it("rejects 0 B and 25 MB + 1 B, accepts exactly 25 MB", () => {
    expect(validateAudioFile(f("a.wav", "audio/wav", 0))).toMatch(/empty/i);
    expect(validateAudioFile(f("a.wav", "audio/wav", MAX_AUDIO_BYTES + 1))).toMatch(/25 MB/);
    expect(validateAudioFile(f("a.wav", "audio/wav", MAX_AUDIO_BYTES))).toBeNull();
  });
  it("rejects other types, unknown MIME, and extension/type mismatches", () => {
    expect(validateAudioFile(f("a.txt", "text/plain"))).toMatch(/WAV, MP3 or WEBM/);
    expect(validateAudioFile(f("a.wav", ""))).toMatch(/WAV, MP3 or WEBM/);
    expect(validateAudioFile(f("a.wav", "audio/mpeg"))).toMatch(/doesn't match/);
  });
  it("normalises media types", () => {
    expect(baseMediaType("Audio/WebM; codecs=opus")).toBe("audio/webm");
  });
});

describe("audio/vnd.wave (what Firefox on Linux reports for a .wav)", () => {
  it("is accepted for .wav, but not as a stand-in for other extensions", () => {
    expect(validateAudioFile(f("a.wav", "audio/vnd.wave"))).toBeNull();
    expect(validateAudioFile(f("a.mp3", "audio/vnd.wave"))).toMatch(/doesn't match/i);
  });

  it("canonicalises the alias, parameters and case, and leaves other types alone", () => {
    expect(canonicalMediaType("audio/vnd.wave")).toBe("audio/wav");
    expect(canonicalMediaType("Audio/Vnd.Wave; x=1")).toBe("audio/wav");
    expect(canonicalMediaType("audio/x-wav")).toBe("audio/x-wav");
    expect(canonicalMediaType("")).toBe("");
  });

  it("re-types the file for upload without touching its bytes, name or date", async () => {
    const original = new File([new Uint8Array([1, 2, 3])], "a.wav", {
      type: "audio/vnd.wave",
      lastModified: 42,
    });
    const out = canonicalAudioFile(original);
    expect(out.type).toBe("audio/wav");
    expect(out.name).toBe("a.wav");
    expect(out.lastModified).toBe(42);
    const bytes = await new Promise<ArrayBuffer>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.readAsArrayBuffer(out);
    });
    expect(new Uint8Array(bytes)).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("returns the very same File when no alias is involved", () => {
    const file = new File([new Uint8Array(2)], "a.wav", { type: "audio/wav" });
    expect(canonicalAudioFile(file)).toBe(file);
  });
});
