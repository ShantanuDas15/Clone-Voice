"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/lib/api/health";

export const HEALTH_POLL_MS = 60_000;

/** Non-blocking banner shown while `/health/ready` reports degraded (R17, F23). */
export function DegradedBanner() {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: HEALTH_POLL_MS,
    retry: false,
  });

  if (data !== "degraded") return null;
  return (
    <div
      role="status"
      className="border-b border-border bg-warning px-4 py-2 text-center text-sm text-warning-foreground"
    >
      CloneVoice is experiencing problems. Uploading and generating may be unavailable for now.
    </div>
  );
}
