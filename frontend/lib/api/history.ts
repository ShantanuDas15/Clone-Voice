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
): Promise<HistoryPage> {
  const response = await http.get<Generation[]>("/synthesize/history", {
    params: { limit, offset },
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
