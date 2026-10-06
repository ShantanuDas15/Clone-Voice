/**
 * Browser-recording helpers (plan §7 Phase 6, R10). The backend accepts WAV/MP3/WEBM only
 * (G-08), so recording is offered only where MediaRecorder can produce WEBM (Chromium, Firefox;
 * not Safari/iOS).
 */

/** Speech is trimmed server-side and ≥ 2 s must remain; the docs recommend 10-30 s. */
export const MIN_RECORDING_SECONDS = 5;
/** Well under the 300 s / 25 MB server limits (opus WEBM is a few hundred KB per minute). */
export const MAX_RECORDING_SECONDS = 120;

const WEBM_TYPES = ["audio/webm;codecs=opus", "audio/webm"] as const;

/** First WEBM type this browser can record, or null (Safari/iOS emit MP4, which the API rejects). */
export function pickRecordingMimeType(): string | null {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return null;
  }
  return WEBM_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? null;
}

export type RecordingSupport =
  { supported: true; mimeType: string } | { supported: false; reason: string };

/** Feature detection with a user-readable reason when recording is unavailable. */
export function detectRecordingSupport(): RecordingSupport {
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return {
      supported: false,
      reason: "Recording needs a secure (HTTPS) connection. You can upload a file instead.",
    };
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    return {
      supported: false,
      reason: "Your browser can't record audio here. You can upload a file instead.",
    };
  }
  const mimeType = pickRecordingMimeType();
  if (!mimeType) {
    return {
      supported: false,
      reason:
        "Your browser records in a format we can't accept (Safari and iOS). Upload a WAV, MP3 or WEBM file instead.",
    };
  }
  return { supported: true, mimeType };
}

/** Copy for a getUserMedia / MediaRecorder failure, by DOMException name. */
export function micErrorMessage(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone access was blocked. Allow it in your browser's site settings, then try again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone was found. Connect one and try again.";
    case "NotReadableError":
    case "AbortError":
      return "Your microphone is busy or unavailable. Close other apps using it and try again.";
    default:
      return "Couldn't start recording. You can upload a file instead.";
  }
}

/** Wrap a recorded blob as an upload `File` with the plain `audio/webm` type the server expects. */
export function recordingToFile(blob: Blob): File {
  return new File([blob], "recording.webm", { type: "audio/webm" });
}

/** `m:ss` for a timer display. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
