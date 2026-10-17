import { http, longRequest } from "@/lib/api/http";
import { canonicalAudioFile } from "@/lib/validation/audio";

/** One thing the user can fix in a recording (`severity` is `warning` or `poor`). */
export interface QualityHint {
  code: string;
  severity: string;
  message: string;
}

/** How well a recording suits cloning: `good` (no hints), `fair` (warnings) or `poor`. */
export interface QualityReport {
  rating: string;
  hints: QualityHint[];
}

/** One clip of a profile and how it compares with the others. */
export interface VoiceSample {
  position: number;
  agreement: number;
  /** True when the clip may be a different speaker from the rest (needs 3+ clips). */
  mismatch: boolean;
  quality?: QualityReport | null;
}

export interface VoiceProfile {
  id: string;
  name: string;
  /** `ready`, `failed`, or (documented but never set by the backend) `processing`. */
  status: string;
  consent_confirmed_at: string;
  terms_version: string;
  created_at: string;
  samples?: VoiceSample[];
}

/** The upload response: the profile plus the lowest-rated clip's report, when it could be made. */
export interface VoiceProfileUpload extends VoiceProfile {
  quality?: QualityReport | null;
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
  /** One or more clips of the same speaker; one is sent as `file`, several as `files`. */
  files: File[];
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
): Promise<VoiceProfileUpload> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("consent_confirmed", "true");
  if (input.termsVersion) form.append("terms_version", input.termsVersion);
  const field = input.files.length === 1 ? "file" : "files";
  for (const f of input.files) form.append(field, canonicalAudioFile(f));
  const { data } = await http.post<VoiceProfileUpload>("/voice/upload", form, {
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

/**
 * Add clips of the same speaker to an existing profile; the embedding is re-derived over every
 * clip. Atomic on the server: a bad clip leaves the profile unchanged.
 */
export async function addClips(
  id: string,
  input: { files: File[]; termsVersion: string | null },
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<VoiceProfileUpload> {
  const form = new FormData();
  form.append("consent_confirmed", "true");
  if (input.termsVersion) form.append("terms_version", input.termsVersion);
  const field = input.files.length === 1 ? "file" : "files";
  for (const f of input.files) form.append(field, canonicalAudioFile(f));
  const { data } = await http.post<VoiceProfileUpload>(
    `/voice/profiles/${encodeURIComponent(id)}/samples`,
    form,
    {
      ...longRequest,
      signal: options.signal,
      onUploadProgress: (e) => options.onProgress?.(e.total ? e.loaded / e.total : 0),
    },
  );
  return data;
}

/** Remove one clip (never the last); the embedding is re-derived from the rest. */
export async function removeClip(id: string, position: number): Promise<VoiceProfileUpload> {
  const { data } = await http.delete<VoiceProfileUpload>(
    `/voice/profiles/${encodeURIComponent(id)}/samples/${position}`,
  );
  return data;
}
