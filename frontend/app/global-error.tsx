"use client";

import { useEffect } from "react";

import "./globals.css";

import { ErrorFallback } from "@/components/error-fallback";
import { reportErrorLazy } from "@/lib/observability/lazy";

export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => {
    reportErrorLazy(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <ErrorFallback reset={reset} />
      </body>
    </html>
  );
}
