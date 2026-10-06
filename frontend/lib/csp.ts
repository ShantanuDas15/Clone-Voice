/**
 * Content-Security-Policy builder (plan §5.9). Pure so it can be unit-tested; `middleware.ts`
 * supplies a fresh nonce per request. Scripts are nonce-gated (no `unsafe-inline`); only
 * development adds `unsafe-eval`, which React's dev tooling needs.
 */

/** Hosts that serve Google profile pictures (`avatar_url` may be an external URL). */
const AVATAR_HOSTS = ["https://lh3.googleusercontent.com"];

/**
 * Sonner injects one `<style>` element at runtime without a nonce (it has no nonce option): it
 * is created empty (hash of "") and then filled with its stylesheet. Both hashes are allowed
 * rather than `'unsafe-inline'`. `tests/csp.test.ts` recomputes the stylesheet hash from the
 * installed sonner, so a sonner upgrade that changes its CSS fails a test instead of silently
 * dropping toast styles under an enforced CSP.
 */
export const STYLE_HASHES = [
  "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='", // empty element, as created
  "'sha256-StEaX+se6YS7pqjzrzMIA0KaX9zF/8zAhvQXZAe5epY='", // sonner stylesheet
] as const;

export interface CspOptions {
  nonce: string;
  /** API origin (scheme + host) the browser may call; `NEXT_PUBLIC_API_BASE_URL`'s origin. */
  apiOrigin: string;
  development?: boolean;
}

export function buildCsp({ nonce, apiOrigin, development = false }: CspOptions): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      ...(development ? ["'unsafe-eval'"] : []),
    ],
    "style-src": ["'self'", `'nonce-${nonce}'`, ...STYLE_HASHES],
    "img-src": ["'self'", "data:", "blob:", ...AVATAR_HOSTS],
    "font-src": ["'self'"],
    "connect-src": ["'self'", apiOrigin],
    "media-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(" ")}`)
    .join("; ");
}

/** Header name: report-only during the soak (default), enforcing once `CSP_ENFORCE=1`. */
export function cspHeaderName(enforce: boolean): string {
  return enforce ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only";
}

/** A fresh, unguessable nonce (base64 of a UUID, per the Next.js CSP guide). */
export function generateNonce(): string {
  return btoa(crypto.randomUUID());
}
