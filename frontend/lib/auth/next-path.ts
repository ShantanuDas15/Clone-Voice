export const DEFAULT_NEXT = "/dashboard";

/**
 * Validate a post-login `next` target as a same-origin relative path (open-redirect
 * prevention). Anything else falls back to the dashboard.
 */
export function sanitizeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || /[\\\u0000-\u001f]/.test(next)) {
    return DEFAULT_NEXT;
  }
  try {
    const base = "http://localhost.invalid";
    const url = new URL(next, base);
    if (url.origin !== base) return DEFAULT_NEXT;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return DEFAULT_NEXT;
  }
}
