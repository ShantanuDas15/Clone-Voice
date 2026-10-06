import { z } from "zod";

/** Mirrors `audio_processing.py`: WAV/MP3/WEBM, non-empty, at most 25 MB. */
export const MAX_AUDIO_BYTES = 25 * 1024 * 1024;
export const NAME_MAX = 255;

const ALLOWED: Readonly<Record<string, readonly string[]>> = {
  ".wav": ["audio/wav", "audio/x-wav", "audio/wave"],
  ".mp3": ["audio/mpeg", "audio/mp3"],
  ".webm": ["audio/webm"],
};

/** Media type without parameters (`audio/webm;codecs=opus` → `audio/webm`), as the server compares it. */
export function baseMediaType(type: string): string {
  return type.split(";", 1)[0]?.trim().toLowerCase() ?? "";
}

/** Client-side pre-check of an audio file; returns a message, or null when it looks acceptable. */
export function validateAudioFile(file: Pick<File, "name" | "size" | "type">): string | null {
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_AUDIO_BYTES) return "That file is larger than 25 MB.";
  const type = baseMediaType(file.type);
  const allowed = Object.values(ALLOWED).some((types) => types.includes(type));
  if (!allowed) return "Use a WAV, MP3 or WEBM audio file.";
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (ext && ALLOWED[ext] && !ALLOWED[ext].includes(type)) {
    return "The file's type doesn't match its extension.";
  }
  return null;
}

export const voiceNameSchema = z
  .string()
  .trim()
  .min(1, "Enter a name for this voice")
  .max(NAME_MAX, `Name must be at most ${NAME_MAX} characters`);
