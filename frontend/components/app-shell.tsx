import Link from "next/link";
import type { ReactNode } from "react";

import { MobileTabs } from "@/components/mobile-tabs";
import { UserMenu } from "@/components/user-menu";
import { DegradedBanner } from "@/components/degraded-banner";
import { OfflineBanner } from "@/components/offline-banner";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import type { Theme } from "@/lib/theme";

/** Page chrome: skip-link, degraded banner, header, main landmark, footer, verification notice. */
export function AppShell({ children, theme }: { children: ReactNode; theme: Theme }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <OfflineBanner />
      <DegradedBanner />
      <header className="border-b border-border">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-5xl flex-col items-start gap-y-1 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-4 sm:gap-y-2"
        >
          <Link href="/">
            <Logo />
          </Link>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <UserMenu />
            <ThemeToggle initial={theme} />
          </div>
        </nav>
      </header>
      <main id="main" className="mx-auto min-h-[70vh] max-w-5xl px-4 py-8">
        {children}
      </main>
      <footer className="border-t border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Generated voices are AI-synthesized. Use only voices you have consent to clone.
      </footer>
      {/* After the footer: fixed bar plus a spacer, so it appears with the session without moving
          anything above it (CLS). */}
      <MobileTabs />
    </>
  );
}
