"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchCapabilities } from "@/lib/api/synthesize";

export const CAPABILITIES_KEY = ["synthesis-capabilities"] as const;

/** What synthesis can do for this user; the delivery controls show only when it says so. */
export function useCapabilities() {
  return useQuery({
    queryKey: CAPABILITIES_KEY,
    queryFn: ({ signal }) => fetchCapabilities(signal),
    staleTime: 5 * 60_000,
    retry: false, // a failure just means no extra controls
  });
}
