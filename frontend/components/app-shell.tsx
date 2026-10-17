import Link from "next/link";
import type { ReactNode } from "react";

import { RouteFocus } from "@/components/route-focus";
import { MobileTabs } from "@/components/mobile-tabs";
import { UserMenu } from "@/components/user-menu";
import { DegradedBanner } from "@/components/degraded-banner";
import { OfflineBanner } from "@/components/offline-banner";
import { Logo } from "@/components/logo";
import { SiteFooter } from "@/components/site-footer";
import { ThemeToggle } from "@/components/theme-toggle";
import type { Theme } from "@/lib/theme";

/** Page chrome: skip-link, degraded banner, header, main landmark, footer, verification notice. */
export function AppShell({ children, theme }: { children: ReactNode; theme: Theme }) {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <RouteFocus />
      <OfflineBanner />
      <DegradedBanner />
      <header className="border-b border-border bg-surface">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-5xl flex-col items-start gap-y-1 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-4 sm:gap-y-2"
        >
          <Link href="/" className="inline-flex min-h-11 items-center">
            <Logo />
          </Link>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <UserMenu />
            <ThemeToggle initial={theme} />
          </div>
        </nav>
      </header>
      <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        {children}
      </main>
      <SiteFooter />
      {/* After the footer: fixed bar plus a spacer, so it appears with the session without moving
          anything above it (CLS). */}
      <MobileTabs />
    </div>
  );
}
