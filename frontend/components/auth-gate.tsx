"use client";

import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useRef } from "react";

import { useAuth } from "@/components/auth-provider";

/** Client-side route gate: the API-host refresh cookie is invisible to the Next.js server. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { status, signedOutOnPurpose } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  // True once this page has seen a signed-in session, so a later sign-out we did not cause means
  // the session ended under the user (expiry, or sign-out in another tab) and sign-in can say so.
  const wasSignedIn = useRef(false);
  if (status === "authenticated") wasSignedIn.current = true;

  useEffect(() => {
    if (status === "unauthenticated") {
      // A deliberate sign-out or account deletion goes home; an expired session goes to sign-in.
      const next = encodeURIComponent(pathname);
      router.replace(
        signedOutOnPurpose
          ? "/"
          : `/login?${wasSignedIn.current ? "reason=expired&" : ""}next=${next}`,
      );
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
