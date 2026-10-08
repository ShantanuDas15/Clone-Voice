"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth-provider";

/**
 * Return page for the Google flow. The provider's bootstrap already exchanged the new refresh
 * cookie for an access token; we only route on the outcome. If no session exists, the browser
 * most likely dropped the cookie, so the login page shows cookie help.
 */
export function GoogleCallback() {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/generate");
    else if (status === "unauthenticated") router.replace("/login?error=session_unavailable");
  }, [status, router]);

  return (
    <p role="status" aria-live="polite">
      Finishing sign-in…
    </p>
  );
}
