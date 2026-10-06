"use client";

import { useRef } from "react";

/**
 * Extract `token` from a URL fragment such as `#token=abc`. Returns null if absent or empty.
 * Tokens travel in the fragment so they never reach servers or Referer headers.
 */
export function parseFragmentToken(hash: string): string | null {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const token = params.get("token")?.trim();
  return token ? token : null;
}

/** Read the fragment token and immediately strip the fragment from the address bar. */
export function consumeFragmentToken(): string | null {
  const token = parseFragmentToken(window.location.hash);
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  return token;
}

/**
 * Call inside an effect. Consumes the fragment once per component instance, so React Strict
 * Mode's second effect pass gets the same token instead of an already-stripped URL.
 */
export function useFragmentToken(): () => string | null {
  const ref = useRef<{ token: string | null } | null>(null);
  return () => {
    ref.current ??= { token: consumeFragmentToken() };
    return ref.current.token;
  };
}
