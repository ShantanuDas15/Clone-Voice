import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/errors";

const RETRYABLE_STATUS = new Set([0, 502, 503, 504]);
const MAX_RETRIES = 2;

/** R5: retry idempotent queries only on network errors and 502/503/504, at most twice. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) return false;
  if (!(error instanceof ApiError)) return false;
  if (error.kind === "CANCELLED") return false;
  return RETRYABLE_STATUS.has(error.status);
}

/** Exponential backoff with jitter, capped at 10 s. */
export function retryDelay(attempt: number): number {
  const base = Math.min(1000 * 2 ** attempt, 10_000);
  return base / 2 + Math.random() * (base / 2);
}

/** Build the app QueryClient: queries retry per R5; mutations never auto-retry. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        retryDelay,
        refetchOnWindowFocus: true,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  });
}
