import { describe, expect, it } from "vitest";

import { MAX_AUDIO_BYTES, baseMediaType, validateAudioFile } from "@/lib/validation/audio";

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
