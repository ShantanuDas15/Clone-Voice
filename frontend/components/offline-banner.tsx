"use client";

import { useOnline } from "@/hooks/use-online";

/** Non-blocking notice while the browser is offline; clears itself and data refetches on reconnect. */
export function OfflineBanner() {
  if (useOnline()) return null;
  return (
    <div
      role="status"
      className="border-b border-border bg-warning px-4 py-2 text-center text-sm text-warning-foreground"
    >
      You&apos;re offline. Uploading and generating are paused until your connection is back.
    </div>
  );
}
