import { http, longRequest } from "@/lib/api/http";

export interface SynthesisResult {
  blob: Blob;
  /** Parsed from `Content-Disposition` (exposed by CORS since FE-1); null if unavailable. */
  generationId: string | null;
  filename: string;
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
  input: { voiceProfileId: string; text: string },
  options: { signal?: AbortSignal } = {},
): Promise<SynthesisResult> {
  const response = await http.post<Blob>(
    "/synthesize",
    { voice_profile_id: input.voiceProfileId, text: input.text },
    { ...longRequest, responseType: "blob", signal: options.signal },
  );
  const header = response.headers["content-disposition"] as string | undefined;
  const parsed = parseFilename(header);
  return {
    blob: response.data,
    generationId: parseGenerationId(parsed),
    filename: parsed ?? "clonevoice-speech.wav",
  };
}
