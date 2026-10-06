"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/lib/api/health";

export const HEALTH_POLL_MS = 60_000;

/** True while `/health/ready` reports degraded (R17); shared by the banner and the forms. */
export function useDegraded(): boolean {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: HEALTH_POLL_MS,
    retry: false,
  });
  return data === "degraded";
}
