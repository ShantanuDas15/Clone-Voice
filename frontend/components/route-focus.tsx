"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Moves focus to the page heading after a client-side route change, so keyboard and
 * screen-reader users start at the new page instead of where the old control used to be
 * (UX plan §12, decision 7). It stays out of the way: not on the first load, not for a change
 * that keeps the same path, not while a modal is open, and not if the new page already put focus
 * inside its content.
 */
export function RouteFocus() {
  const pathname = usePathname();
  const previous = useRef(pathname);

  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    if (document.querySelector('[aria-modal="true"]')) return;
    const main = document.querySelector("main");
    const heading = main?.querySelector<HTMLElement>("h1");
    if (!main || !heading) return;
    // A control in the header (the link just followed) keeps focus across the navigation and
    // must not block the move; only focus the new page placed inside <main> itself does.
    if (main.contains(document.activeElement)) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }, [pathname]);

  return null;
}
