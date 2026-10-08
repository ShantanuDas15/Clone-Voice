"use client";

import { useEffect } from "react";

import "./globals.css";

import { ErrorFallback } from "@/components/error-fallback";
import { Logo } from "@/components/logo";
import { reportErrorLazy } from "@/lib/observability/lazy";

/**
 * Last-resort boundary: it replaces the root layout, so it brings its own page chrome (wordmark
 * and footer) and never renders blank. It follows the OS theme (the theme cookie is read in the
 * layout it replaces).
 */
export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => {
    reportErrorLazy(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <header className="border-b border-border">
          <div className="mx-auto max-w-5xl px-4 py-3">
            <Logo />
          </div>
        </header>
        <main className="mx-auto min-h-[70vh] max-w-5xl px-4 py-8">
          <ErrorFallback reset={reset} />
        </main>
        <footer className="border-t border-border px-4 py-6 text-center text-sm text-muted-foreground">
          Generated voices are AI-synthesized. Use only voices you have consent to clone.
        </footer>
      </body>
    </html>
  );
}
