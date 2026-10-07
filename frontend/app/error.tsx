"use client";

import { useEffect } from "react";

import { ErrorFallback } from "@/components/error-fallback";
import { reportErrorLazy } from "@/lib/observability/lazy";

export default function RouteError({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => {
    reportErrorLazy(error);
  }, [error]);

  return <ErrorFallback reset={reset} />;
}
