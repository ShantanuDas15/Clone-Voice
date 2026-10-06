import Link from "next/link";
import type { ReactNode } from "react";

import { DegradedBanner } from "@/components/degraded-banner";

/** Page chrome: skip-link, degraded banner, header, main landmark, footer. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <DegradedBanner />
      <header className="border-b border-border">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3"
        >
          <Link href="/" className="text-lg font-semibold">
            CloneVoice
          </Link>
        </nav>
      </header>
      <main id="main" className="mx-auto min-h-[70vh] max-w-5xl px-4 py-8">
        {children}
      </main>
      <footer className="border-t border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Generated voices are AI-synthesized. Use only voices you have consent to clone.
      </footer>
    </>
  );
}
