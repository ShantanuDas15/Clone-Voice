"use client";

import "./globals.css";

import { ErrorFallback } from "@/components/error-fallback";

export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <ErrorFallback reset={reset} />
      </body>
    </html>
  );
}
