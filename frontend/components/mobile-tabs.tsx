"use client";

import { useAuth } from "@/components/auth-provider";
import { NavLink } from "@/components/nav-link";
import { APP_LINKS } from "@/components/user-menu";

/**
 * Bottom tab bar for signed-in users below `sm` (the header links are hidden there). It is fixed,
 * so it never shifts content; the spacer after the footer keeps the last line reachable.
 */
export function MobileTabs() {
  const { status } = useAuth();
  if (status !== "authenticated") return null;
  return (
    <>
      <div aria-hidden className="h-14 sm:hidden" />
      <nav
        aria-label="Mobile"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background sm:hidden"
      >
        <ul className="mx-auto flex max-w-5xl">
          {APP_LINKS.map(({ href, label }) => (
            <li key={href} className="flex-1">
              <NavLink href={href} className="flex min-h-14 items-center justify-center text-sm">
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
