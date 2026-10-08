export const DEFAULT_NEXT = "/generate";

/** Pre-split routes, still honoured in `next=` targets (next.config.mjs redirects the pages). */
const LEGACY_PATHS: Record<string, string> = { "/dashboard": "/generate", "/profile": "/voices" };

/**
 * Validate a post-login `next` target as a same-origin relative path (open-redirect
 * prevention). Anything else falls back to the generator; renamed routes are mapped.
 */
export function sanitizeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || /[\\\u0000-\u001f]/.test(next)) {
    return DEFAULT_NEXT;
  }
  try {
    const base = "http://localhost.invalid";
    const url = new URL(next, base);
    if (url.origin !== base) return DEFAULT_NEXT;
    const path = LEGACY_PATHS[url.pathname] ?? url.pathname;
    return `${path}${url.search}${url.hash}`;
  } catch {
    return DEFAULT_NEXT;
  }
}
