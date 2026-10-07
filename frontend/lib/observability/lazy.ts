/**
 * Entry points the app calls to report. They load the reporter (and through it the SDK) only
 * when a DSN is configured, so a build without reporting ships none of it in its initial JS.
 */

import { env } from "@/lib/env";
import { ApiError } from "@/lib/errors";

/** Report an unexpected error; a no-op unless `NEXT_PUBLIC_SENTRY_DSN` is set. */
export function reportErrorLazy(error: unknown): void {
  if (!env.NEXT_PUBLIC_SENTRY_DSN) return;
  void import("@/lib/observability/report")
    .then((m) => m.reportError(error))
    .catch(() => undefined);
}

/** Whether an API failure is worth reporting: server faults, not user or network conditions. */
export function isReportableApiError(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 500 && error.status < 600;
}
