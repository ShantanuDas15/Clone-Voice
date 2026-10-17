import { http } from "@/lib/api/http";

export const HISTORY_PAGE_SIZE = 50;

export interface Generation {
  id: string;
  voice_profile_id: string;
  voice_profile_name: string;
  /** `completed` or `failed` (failed rows carry no audio, G-09). */
  status: string;
  input_text: string;
  output_filename: string;
  duration_seconds: number | null;
  /** False once the WAV has been pruned (30-day retention, G-10) or for failed rows. */
  audio_available: boolean;
  created_at: string;
  /** What the request asked for and what the server did with it; null on rows from before each was recorded. */
  engine?: string | null;
  engine_fallback_from?: string | null;
  emotion?: string | null;
  intensity?: number | null;
  style_applied?: boolean | null;
  emotions_used?: string[] | null;
  sound_tags_dropped?: string[] | null;
  seed?: number | null;
  seed_applied?: boolean | null;
}

export interface HistoryPage {
  items: Generation[];
  /** Size of the whole history from `X-Total-Count`; null if the header was unreadable. */
  total: number | null;
  offset: number;
}

/** A row without audio because its generation failed (shown as "Failed — no audio"). */
export function isFailedGeneration(gen: Generation): boolean {
  return gen.status !== "completed" || gen.output_filename === "";
}

/** True if another page may exist: from the total when known, else by page fullness (R12). */
export function hasMoreHistory(page: HistoryPage, limit: number = HISTORY_PAGE_SIZE): boolean {
  if (page.items.length === 0) return false;
  if (page.total !== null) return page.offset + page.items.length < page.total;
  return page.items.length === limit;
}

export async function fetchHistory(
  offset: number,
  signal?: AbortSignal,
  limit: number = HISTORY_PAGE_SIZE,
  voiceProfileId?: string,
): Promise<HistoryPage> {
  const response = await http.get<Generation[]>("/synthesize/history", {
    params: voiceProfileId
      ? { limit, offset, voice_profile_id: voiceProfileId }
      : { limit, offset },
    signal,
  });
  const raw = Number.parseInt(String(response.headers["x-total-count"] ?? ""), 10);
  return { items: response.data, total: Number.isNaN(raw) ? null : raw, offset };
}

/** Fetch a past generation's WAV. Needs the bearer header, so it cannot be a plain `<audio src>`. */
export async function fetchGenerationAudio(id: string, signal?: AbortSignal): Promise<Blob> {
  const { data } = await http.get<Blob>(`/synthesize/${encodeURIComponent(id)}/audio`, {
    responseType: "blob",
    signal,
  });
  return data;
}

/** Delete one generation: its audio file and the text typed for it (backend D1). */
export async function deleteGeneration(id: string): Promise<void> {
  await http.delete(`/synthesize/${encodeURIComponent(id)}`);
}
