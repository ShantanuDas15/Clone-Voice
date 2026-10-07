import { http, longRequest } from "@/lib/api/http";
import { canonicalAudioFile } from "@/lib/validation/audio";

export interface VoiceProfile {
  id: string;
  name: string;
  /** `ready`, `failed`, or (documented but never set by the backend) `processing`. */
  status: string;
  consent_confirmed_at: string;
  terms_version: string;
  created_at: string;
}

/** Profiles come back newest first, but order is not contractually guaranteed (G-09): sort anyway. */
export function sortProfiles(profiles: readonly VoiceProfile[]): VoiceProfile[] {
  return [...profiles].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

export async function fetchProfiles(signal?: AbortSignal): Promise<VoiceProfile[]> {
  const { data } = await http.get<VoiceProfile[]>("/voice/profiles", { signal });
  return sortProfiles(data);
}

export interface UploadInput {
  name: string;
  file: File;
  /** Terms version the user was shown; the server answers 409 if it has changed. */
  termsVersion: string | null;
}

/**
 * Upload a sample. The multipart body is built by the browser (no manual Content-Type) and the
 * File's own MIME type is sent untouched, bar the `audio/vnd.wave` alias (folded into `audio/wav`):
 * the server checks it against the real container.
 * `onProgress` receives 0..1 for the bytes sent; the server then analyses the voice with the
 * request still open.
 */
export async function uploadProfile(
  input: UploadInput,
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<VoiceProfile> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("consent_confirmed", "true");
  if (input.termsVersion) form.append("terms_version", input.termsVersion);
  form.append("file", canonicalAudioFile(input.file));
  const { data } = await http.post<VoiceProfile>("/voice/upload", form, {
    ...longRequest,
    signal: options.signal,
    onUploadProgress: (e) => options.onProgress?.(e.total ? e.loaded / e.total : 0),
  });
  return data;
}

/** Soft-delete a profile; the backend also erases its generations and files. */
export async function deleteProfile(id: string): Promise<void> {
  await http.delete(`/voice/profiles/${encodeURIComponent(id)}`);
}
