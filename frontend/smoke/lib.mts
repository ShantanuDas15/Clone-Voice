/**
 * Release smoke checks (FRONTEND_IMPLEMENTATION_PLAN.md, Phase 8). Pure functions over response
 * headers and URLs so the pass/fail logic is unit-tested without a network; `smoke/run.mts`
 * does the I/O.
 */

export type Level = "pass" | "warn" | "fail";

export interface CheckResult {
  name: string;
  level: Level;
  detail: string;
}

export type Headers = Record<string, string | undefined>;

const result = (name: string, level: Level, detail: string): CheckResult => ({
  name,
  level,
  detail,
});

/** Lower-case the header names so lookups are case-insensitive. */
export function lowerHeaders(h: Headers): Headers {
  return Object.fromEntries(Object.entries(h).map(([k, v]) => [k.toLowerCase(), v]));
}

/**
 * Approximate registrable domain: the last two labels, or the whole host for localhost and IPs.
 * It does not consult the public-suffix list, so `a.co.uk` and `b.co.uk` would wrongly look
 * same-site; the check reports it as a warning-grade heuristic.
 */
export function registrableDomain(hostname: string): string {
  if (hostname === "localhost" || /^[\d.]+$/.test(hostname) || hostname.includes(":")) {
    return hostname;
  }
  return hostname.split(".").slice(-2).join(".");
}

/** The refresh cookie is SameSite=Lax, so it is only sent when both ends share a site. */
export function checkSameSite(webUrl: string, apiUrl: string): CheckResult {
  const web = new URL(webUrl).hostname;
  const api = new URL(apiUrl).hostname;
  const same = registrableDomain(web) === registrableDomain(api);
  return result(
    "web and API are same-site",
    same ? "pass" : "fail",
    same
      ? `${web} and ${api} share ${registrableDomain(web)}`
      : `${web} and ${api} do not share a registrable domain, so the SameSite=Lax refresh cookie will not be sent (G-13)`,
  );
}

/** Security headers every page must carry (plan §5.9). */
export function checkSecurityHeaders(raw: Headers): CheckResult[] {
  const h = lowerHeaders(raw);
  const out: CheckResult[] = [];
  const csp = h["content-security-policy"];
  const cspReportOnly = h["content-security-policy-report-only"];
  if (csp) out.push(result("CSP header", "pass", "enforcing"));
  else if (cspReportOnly) {
    out.push(
      result(
        "CSP header",
        "warn",
        "report-only: flip CSP_ENFORCE=1 once the soak is clean (DoD 6)",
      ),
    );
  } else out.push(result("CSP header", "fail", "no Content-Security-Policy header"));

  const policy = csp ?? cspReportOnly ?? "";
  if (policy) {
    const bad = ["'unsafe-inline'", "'unsafe-eval'"].filter((t) => policy.includes(t));
    out.push(
      result(
        "CSP has no unsafe-inline/unsafe-eval",
        bad.length ? "fail" : "pass",
        bad.length ? `found ${bad.join(", ")}` : "scripts are nonce-gated",
      ),
    );
  }
  out.push(
    h["x-content-type-options"]?.toLowerCase() === "nosniff"
      ? result("X-Content-Type-Options", "pass", "nosniff")
      : result("X-Content-Type-Options", "fail", "missing or not nosniff"),
  );
  out.push(
    h["x-frame-options"] || policy.includes("frame-ancestors")
      ? result("clickjacking protection", "pass", "frame-ancestors or X-Frame-Options")
      : result("clickjacking protection", "fail", "no frame-ancestors / X-Frame-Options"),
  );
  return out;
}

/** The token pages must not leak the URL fragment's context through `Referer`. */
export function checkFragmentPageReferrer(raw: Headers): CheckResult {
  const value = lowerHeaders(raw)["referrer-policy"];
  return value?.toLowerCase() === "no-referrer"
    ? result("fragment pages send Referrer-Policy: no-referrer", "pass", value)
    : result(
        "fragment pages send Referrer-Policy: no-referrer",
        "fail",
        `got ${value ?? "no header"} (emailed-token pages must send no-referrer)`,
      );
}

/** Preflight and simple-request CORS for the web origin, with credentials. */
export function checkCors(preflight: Headers, simple: Headers, webOrigin: string): CheckResult[] {
  const pre = lowerHeaders(preflight);
  const sim = lowerHeaders(simple);
  const out: CheckResult[] = [];
  const allowed = pre["access-control-allow-origin"];
  out.push(
    allowed === webOrigin
      ? result("CORS preflight allows the web origin", "pass", allowed)
      : result(
          "CORS preflight allows the web origin",
          "fail",
          `Access-Control-Allow-Origin is ${allowed ?? "absent"}, expected ${webOrigin}; fix ALLOWED_ORIGINS`,
        ),
  );
  out.push(
    pre["access-control-allow-credentials"] === "true"
      ? result("CORS allows credentials", "pass", "true")
      : result("CORS allows credentials", "fail", "Access-Control-Allow-Credentials is not true"),
  );
  const exposed = (sim["access-control-expose-headers"] ?? "").toLowerCase();
  out.push(
    exposed.includes("content-disposition")
      ? result("CORS exposes Content-Disposition", "pass", exposed)
      : result(
          "CORS exposes Content-Disposition",
          "fail",
          "download filename and generation id would be unreadable",
        ),
  );
  return out;
}

export interface SetCookie {
  name: string;
  attributes: string[];
}

/** Parse a `Set-Cookie` header value into a name and lower-cased attribute list. */
export function parseSetCookie(header: string): SetCookie {
  const [pair = "", ...rest] = header.split(";").map((p) => p.trim());
  return {
    name: pair.split("=")[0] ?? "",
    attributes: rest.map((a) => a.toLowerCase()),
  };
}

/** The refresh cookie must be httpOnly + SameSite=Lax, and Secure on https. */
export function checkRefreshCookie(setCookies: string[], https: boolean): CheckResult[] {
  const cookie = setCookies.map(parseSetCookie).find((c) => c.name === "refresh_token");
  if (!cookie) return [result("refresh cookie is set", "fail", "no refresh_token Set-Cookie")];
  const has = (a: string) => cookie.attributes.includes(a);
  return [
    result("refresh cookie is set", "pass", "refresh_token"),
    has("httponly")
      ? result("refresh cookie HttpOnly", "pass", "yes")
      : result("refresh cookie HttpOnly", "fail", "readable by scripts"),
    has("samesite=lax")
      ? result("refresh cookie SameSite=Lax", "pass", "yes")
      : result("refresh cookie SameSite=Lax", "fail", cookie.attributes.join("; ")),
    https
      ? has("secure")
        ? result("refresh cookie Secure", "pass", "yes")
        : result("refresh cookie Secure", "fail", "missing on an https deployment")
      : result("refresh cookie Secure", "warn", "not checked: http deployment"),
  ];
}

/** `/metrics` must not be readable without its token on a public host. */
export function checkMetricsProtected(status: number): CheckResult {
  return status === 200
    ? result(
        "/metrics requires a token",
        "warn",
        "readable without a token; set METRICS_AUTH_TOKEN",
      )
    : result("/metrics requires a token", "pass", `status ${status} without a token`);
}

/** Exit code: 1 on any failure; warnings alone pass. */
export function exitCode(results: CheckResult[]): number {
  return results.some((r) => r.level === "fail") ? 1 : 0;
}
