"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** True when `pathname` is `href` or a sub-route of it. */
export function isCurrent(pathname: string | null, href: string): boolean {
  return pathname === href || (pathname?.startsWith(`${href}/`) ?? false);
}

/** Primary-nav link that exposes the current page to assistive tech and marks it visibly. */
export function NavLink({ href, children }: { href: string; children: ReactNode }) {
  const current = isCurrent(usePathname(), href);
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={`underline-offset-4 hover:underline ${current ? "font-semibold underline" : ""}`}
    >
      {children}
    </Link>
  );
}
