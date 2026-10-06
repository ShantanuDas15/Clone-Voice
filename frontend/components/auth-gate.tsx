"use client";

import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useAuth } from "@/components/auth-provider";

/** Client-side route gate: the API-host refresh cookie is invisible to the Next.js server. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { status, signedOutOnPurpose } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "unauthenticated") {
      // A deliberate sign-out or account deletion goes home; an expired session goes to sign-in.
      router.replace(signedOutOnPurpose ? "/" : `/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, signedOutOnPurpose, router, pathname]);

  if (status !== "authenticated") {
    return (
      <div role="status" aria-live="polite" className="space-y-3 py-8">
        <span className="sr-only">Loading your session…</span>
        <div className="h-8 w-48 animate-pulse rounded bg-muted" />
        <div className="h-4 w-full max-w-md animate-pulse rounded bg-muted" />
      </div>
    );
  }
  return <>{children}</>;
}
