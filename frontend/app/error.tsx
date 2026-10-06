"use client";

import { ErrorFallback } from "@/components/error-fallback";

export default function RouteError({ reset }: { error: Error; reset: () => void }) {
  return <ErrorFallback reset={reset} />;
}
