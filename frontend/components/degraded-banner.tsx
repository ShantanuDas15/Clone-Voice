"use client";

import { HEALTH_POLL_MS, useDegraded } from "@/hooks/use-health";
import { BRAND_NAME } from "@/lib/brand";

export { HEALTH_POLL_MS };

/** Non-blocking banner shown while `/health/ready` reports degraded (R17, F23). */
export function DegradedBanner() {
  if (!useDegraded()) return null;
  return (
    <div
      role="status"
      className="border-b border-border bg-warning px-4 py-2 text-center text-sm text-warning-foreground"
    >
      {BRAND_NAME} is experiencing problems. Uploading and generating may be unavailable for now.
    </div>
  );
}
