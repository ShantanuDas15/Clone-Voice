import { http, longRequest } from "@/lib/api/http";

export interface SynthesisResult {
  blob: Blob;
  /** Parsed from `Content-Disposition` (exposed by CORS since FE-1); null if unavailable. */
  generationId: string | null;
  filename: string;
  /** `applied`/`ignored` when an emotion was requested (`X-Voice-Style`); null otherwise. */
  styleApplied: boolean | null;
  /** One label per sentence (`X-Voice-Emotions`), empty when the engine did not report them. */
  emotions: string[];
  /** Sound tags the engine could not make (`X-Voice-Tags-Dropped`). */
  tagsDropped: string[];
}

export interface SynthesisInput {
  voiceProfileId: string;
  text: string;
  /** Left out of the request for `auto`, so old behaviour is unchanged. */
  emotion?: string;
  /** 0 to 1; only sent together with a named emotion other than neutral. */
  intensity?: number;
}

export interface SynthesisCapabilities {
  /** True when a chosen emotion would be applied for this user; false means it is ignored. */
  emotion_control: boolean;
}

export async function fetchCapabilities(signal?: AbortSignal): Promise<SynthesisCapabilities> {
  const { data } = await http.get<SynthesisCapabilities>("/synthesize/capabilities", { signal });
  return data;
}

/** Split a comma-separated header into trimmed, non-empty values. */
export function parseList(value: unknown): string[] {
  return typeof value === "string"
    ? value
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean)
    : [];
}

const FILENAME_RE = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i;
const GENERATION_ID_RE = /^synthesized_([0-9a-f-]{36})\.wav$/i;

/** Extract the filename from a `Content-Disposition` header value. */
export function parseFilename(contentDisposition: string | undefined | null): string | null {
  const match = contentDisposition ? FILENAME_RE.exec(contentDisposition) : null;
  const name = match?.[1]?.trim();
  return name ? name : null;
}

/** The new generation's id, which the backend embeds in the download filename. */
export function parseGenerationId(filename: string | null): string | null {
  return (filename && GENERATION_ID_RE.exec(filename)?.[1]) || null;
}

/**
 * Generate speech. One synchronous, long-running request: there is no job id, progress or
 * server-side cancel, so aborting only stops the browser waiting (R7). Never auto-retried (R5).
 */
export async function synthesize(
  input: SynthesisInput,
  options: { signal?: AbortSignal } = {},
): Promise<SynthesisResult> {
  const response = await http.post<Blob>(
    "/synthesize",
    {
      voice_profile_id: input.voiceProfileId,
      text: input.text,
      ...(input.emotion && input.emotion !== "auto" ? { emotion: input.emotion } : {}),
      ...(input.intensity !== undefined ? { intensity: input.intensity } : {}),
    },
    { ...longRequest, responseType: "blob", signal: options.signal },
  );
  const header = response.headers["content-disposition"] as string | undefined;
  const parsed = parseFilename(header);
  return {
    blob: response.data,
    generationId: parseGenerationId(parsed),
    filename: parsed ?? "clonevoice-speech.wav",
    styleApplied:
      response.headers["x-voice-style"] === undefined
        ? null
        : response.headers["x-voice-style"] === "applied",
    emotions: parseList(response.headers["x-voice-emotions"]),
    tagsDropped: parseList(response.headers["x-voice-tags-dropped"]),
  };
}
