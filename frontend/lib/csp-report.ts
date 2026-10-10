/**
 * Scrubbing and limiting for CSP violation reports (UX plan §12 M3). The endpoint is public and
 * unauthenticated by necessity (browsers send reports without credentials), so everything that
 * reaches a log line is rebuilt from an allow-list of fixed fields: no raw string from the
 * request is ever logged as-is.
 */

export const MAX_BODY_BYTES = 4096;
export const MAX_REPORTS_PER_REQUEST = 10;
const MAX_FIELD = 200;

export interface ScrubbedReport {
  directive: string;
  blocked: string;
  page: string;
  disposition: "enforce" | "report" | "unknown";
}

/** Keep printable ASCII only (this removes newlines, escapes and bidi/control tricks), then cap. */
function printable(value: unknown, max = MAX_FIELD): string {
  return String(value ?? "")
    .replace(/[^\x20-\x7e]/g, "_")
    .slice(0, max);
}

/** `scheme://host/path` of a URL, with credentials, query and fragment dropped. */
function originAndPath(value: unknown): string {
  const raw = typeof value === "string" ? value : "";
  if (!raw) return "";
  // Keywords browsers report instead of a URL: inline, eval, data, blob, self, wasm-eval...
  if (/^[a-z-]{1,20}$/.test(raw)) return raw;
  try {
    const u = new URL(raw);
    if (u.protocol === "data:" || u.protocol === "blob:" || u.protocol === "about:") {
      return `${u.protocol}`;
    }
    return printable(`${u.protocol}//${u.host}${u.pathname}`);
  } catch {
    return "invalid";
  }
}

function directiveOf(value: unknown): string {
  return typeof value === "string" && /^[a-z-]{1,40}$/.test(value) ? value : "unknown";
}

function pathOf(value: unknown): string {
  return typeof value === "string" ? originAndPath(value).replace(/^[a-z]+:\/\/[^/]*/, "") : "";
}

function dispositionOf(value: unknown): ScrubbedReport["disposition"] {
  return value === "enforce" || value === "report" ? value : "unknown";
}

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Legacy `report-uri` body: `{ "csp-report": { "effective-directive": ... } }`. */
function fromLegacy(body: unknown): ScrubbedReport[] {
  const r = isObject(body) ? body["csp-report"] : undefined;
  if (!isObject(r)) return [];
  return [
    {
      directive: directiveOf(
        r["effective-directive"] ?? r["violated-directive"]?.toString().split(" ")[0],
      ),
      blocked: originAndPath(r["blocked-uri"]),
      page: pathOf(r["document-uri"]),
      disposition: dispositionOf(r["disposition"]),
    },
  ];
}

/** `report-to` body: an array of `{ type: "csp-violation", body: { effectiveDirective, ... } }`. */
function fromReporting(body: unknown): ScrubbedReport[] {
  if (!Array.isArray(body)) return [];
  return body
    .filter((e): e is Json => isObject(e) && e.type === "csp-violation" && isObject(e.body))
    .map((e) => {
      const b = e.body as Json;
      return {
        directive: directiveOf(b.effectiveDirective),
        blocked: originAndPath(b.blockedURL),
        page: pathOf(b.documentURL),
        disposition: dispositionOf(b.disposition),
      };
    });
}

/**
 * Parse a request body into scrubbed reports. Anything that is not a recognised CSP report
 * (wrong type, malformed JSON, unexpected shape, too large) yields an empty list, never an error.
 */
export function parseCspReports(contentType: string | null, text: string): ScrubbedReport[] {
  if (text.length > MAX_BODY_BYTES) return [];
  const type = (contentType ?? "").split(";")[0]?.trim().toLowerCase();
  if (type !== "application/csp-report" && type !== "application/reports+json") return [];
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return [];
  }
  const reports = type === "application/csp-report" ? fromLegacy(body) : fromReporting(body);
  return reports.slice(0, MAX_REPORTS_PER_REQUEST);
}

/**
 * A small in-memory limiter: a per-client budget plus a global one. The global budget is the
 * real defence, because the client key comes from a spoofable `X-Forwarded-For`; rotating it can
 * defeat the per-client budget but never the global one. State is per instance (best effort).
 */
export class ReportLimiter {
  private perClient = new Map<string, { count: number; reset: number }>();
  private global = { count: 0, reset: 0 };

  constructor(
    private readonly perClientMax = 20,
    private readonly globalMax = 120,
    private readonly windowMs = 60_000,
    private readonly maxKeys = 1000,
  ) {}

  allow(client: string, now = Date.now()): boolean {
    if (now >= this.global.reset) this.global = { count: 0, reset: now + this.windowMs };
    if (this.global.count >= this.globalMax) return false;
    if (this.perClient.size >= this.maxKeys) this.perClient.clear(); // bounded memory
    let entry = this.perClient.get(client);
    if (!entry || now >= entry.reset) {
      entry = { count: 0, reset: now + this.windowMs };
      this.perClient.set(client, entry);
    }
    if (entry.count >= this.perClientMax) return false;
    entry.count += 1;
    this.global.count += 1;
    return true;
  }
}

/** The caller's address as the proxy reports it; only used as a limiter key, never logged. */
export function clientKey(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return printable(forwarded || headers.get("x-real-ip") || "unknown", 64);
}
