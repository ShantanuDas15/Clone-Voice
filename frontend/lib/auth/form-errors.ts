import type { ApiError } from "@/lib/errors";

/** Copy for a rate-limited response, with a countdown hint only when the server sent one. */
export function rateLimitMessage(error: ApiError): string {
  if (error.retryAfterSec) {
    const mins = Math.ceil(error.retryAfterSec / 60);
    const wait =
      error.retryAfterSec < 60
        ? `${error.retryAfterSec} seconds`
        : `${mins} minute${mins > 1 ? "s" : ""}`;
    return `Too many attempts. Please try again in ${wait}.`;
  }
  return "Too many attempts. Please wait a moment and try again.";
}
