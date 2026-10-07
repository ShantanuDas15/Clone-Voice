/**
 * Error and web-vitals reporting (plan Phase 7 task 6).
 *
 * Off unless `NEXT_PUBLIC_SENTRY_DSN` is set. The SDK is imported dynamically so it never
 * counts toward the public routes' JS budget, and it runs with no default integrations: no
 * console, DOM-click or fetch breadcrumbs, no request context. Every event goes through
 * `scrubEvent`. Failures here are swallowed; reporting must never break the app.
 */

import { env } from "@/lib/env";
import { ApiError } from "@/lib/errors";
import { scrubEvent, scrubRoute } from "@/lib/observability/scrub";

type SentryModule = typeof import("@sentry/browser");

const DSN = env.NEXT_PUBLIC_SENTRY_DSN;

let sdk: Promise<SentryModule | null> | undefined;

/** Start the SDK now so its global handlers catch uncaught errors and rejections. */
export async function initReporting(): Promise<void> {
  await load();
}

/** Whether reporting is configured for this build. */
export function reportingEnabled(): boolean {
  return Boolean(DSN);
}

function load(): Promise<SentryModule | null> {
  if (!DSN) return Promise.resolve(null);
  sdk ??= import("@sentry/browser")
    .then((Sentry) => {
      Sentry.init({
        dsn: DSN,
        environment: process.env.NODE_ENV,
        sendDefaultPii: false,
        defaultIntegrations: false,
        integrations: [Sentry.globalHandlersIntegration(), Sentry.dedupeIntegration()],
        maxBreadcrumbs: 0,
        beforeBreadcrumb: () => null,
        beforeSend: (event) => scrubEvent(event),
      });
      return Sentry;
    })
    .catch(() => null);
  return sdk;
}

function currentRoute(): string {
  return typeof window === "undefined" ? "" : scrubRoute(window.location.pathname);
}

/**
 * Report an unexpected error. An `ApiError` is reduced to its status, kind and request id,
 * because its message is server text that can echo what the user submitted.
 */
export async function reportError(error: unknown): Promise<void> {
  try {
    const Sentry = await load();
    if (!Sentry) return;
    const tags: Record<string, string | number> = { route: currentRoute() };
    let toSend: Error;
    if (error instanceof ApiError) {
      toSend = new Error(`ApiError ${error.status} ${error.kind}`);
      toSend.name = "ApiError";
      tags.status = error.status;
      tags.kind = error.kind;
      if (error.requestId) tags.request_id = error.requestId;
    } else {
      toSend = error instanceof Error ? error : new Error("Non-error value thrown");
    }
    Sentry.captureException(toSend, { tags });
  } catch {
    // Reporting is best effort.
  }
}

export interface VitalMetric {
  name: string;
  value: number;
  rating?: string;
}

/** Report a web vital only when it is not "good", to keep volume and cost low. */
export async function reportVital(metric: VitalMetric): Promise<void> {
  if (!DSN || metric.rating === "good") return;
  try {
    const Sentry = await load();
    if (!Sentry) return;
    Sentry.captureMessage(`web-vital ${metric.name} ${Math.round(metric.value)}`, {
      level: "info",
      tags: { route: currentRoute(), metric: metric.name, rating: metric.rating ?? "unknown" },
    });
  } catch {
    // Best effort.
  }
}
