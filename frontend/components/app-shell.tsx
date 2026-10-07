import Link from "next/link";
import type { ReactNode } from "react";

import { VerificationBanner } from "@/components/verification-banner";
import { UserMenu } from "@/components/user-menu";
import { DegradedBanner } from "@/components/degraded-banner";

/** Page chrome: skip-link, degraded banner, header, main landmark, footer, verification notice. */
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
          className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3"
        >
          <Link href="/" className="text-lg font-semibold">
            CloneVoice
          </Link>
          <UserMenu />
        </nav>
      </header>
      <main id="main" className="mx-auto min-h-[70vh] max-w-5xl px-4 py-8">
        {children}
      </main>
      <footer className="border-t border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Generated voices are AI-synthesized. Use only voices you have consent to clone.
      </footer>
      {/* After the footer, sticky: it appears once the session resolves, and anything above it
          would be pushed down (CLS). Here it only extends the page. */}
      <VerificationBanner />
    </>
  );
}
