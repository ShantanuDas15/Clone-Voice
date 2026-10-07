/**
 * PII scrubber for error reports (plan Phase 7 task 6, Definition of Done 7).
 *
 * Nothing the user typed, uploaded or received by email may leave the browser: no synthesis
 * text, audio, email addresses, passwords or tokens. The reporter is allow-list based: an event
 * keeps only the fields named here, and every string that survives is pattern-scrubbed too.
 */

const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const JWT = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*/g;
/** Long opaque runs (verification/reset tokens, API keys, base64 audio). Short ids pass. */
const OPAQUE = /\b[A-Za-z0-9_-]{32,}\b/g;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** Tag keys an event may carry; anything else is dropped. */
const TAG_ALLOW = new Set(["route", "status", "kind", "request_id", "metric", "rating"]);

/** Redact emails, JWTs and long opaque strings from free text. */
export function scrubString(value: string): string {
  return value.replace(EMAIL, "[email]").replace(JWT, "[token]").replace(OPAQUE, "[token]");
}

/** Collapse a URL or path to its route shape: no origin, query or fragment, ids as `:id`. */
export function scrubRoute(url: string): string {
  let path = url;
  try {
    path = new URL(url, "http://placeholder.invalid").pathname;
  } catch {
    path = url.split(/[?#]/)[0] ?? "";
  }
  return path.replace(UUID, ":id").replace(OPAQUE, ":token");
}

type Json = Record<string, unknown>;

function cleanTags(tags: unknown): Record<string, string> | undefined {
  if (!tags || typeof tags !== "object") return undefined;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tags as Json)) {
    if (TAG_ALLOW.has(key) && (typeof value === "string" || typeof value === "number")) {
      out[key] = scrubString(String(value));
    }
  }
  return out;
}

function cleanException(exception: unknown): unknown {
  const values = (exception as { values?: Json[] } | undefined)?.values;
  if (!Array.isArray(values)) return undefined;
  return {
    values: values.map((v) => ({
      type: typeof v.type === "string" ? v.type : "Error",
      value: typeof v.value === "string" ? scrubString(v.value) : undefined,
      // Frames carry file names and line numbers only; `vars` (local values) is dropped.
      stacktrace: (v.stacktrace as { frames?: Json[] } | undefined)?.frames
        ? {
            frames: (v.stacktrace as { frames: Json[] }).frames.map((f) => ({
              filename: typeof f.filename === "string" ? scrubRoute(f.filename) : undefined,
              function: f.function,
              lineno: f.lineno,
              colno: f.colno,
              in_app: f.in_app,
            })),
          }
        : undefined,
    })),
  };
}

/**
 * Reduce a Sentry event to an allow-list. Used as `beforeSend`: user, request (URL, query,
 * cookies, headers, body), breadcrumbs, extra data and contexts are all discarded.
 */
export function scrubEvent<T extends object>(event: T): T {
  const e = event as Json;
  const clean: Json = {
    event_id: e.event_id,
    timestamp: e.timestamp,
    platform: e.platform,
    level: e.level,
    release: e.release,
    environment: e.environment,
    sdk: e.sdk,
    message: typeof e.message === "string" ? scrubString(e.message) : undefined,
    exception: cleanException(e.exception),
    tags: cleanTags(e.tags),
    // The page is reported as a route only (R16): no query, fragment or id.
    transaction: typeof e.transaction === "string" ? scrubRoute(e.transaction) : undefined,
  };
  for (const key of Object.keys(clean)) if (clean[key] === undefined) delete clean[key];
  return clean as T;
}
