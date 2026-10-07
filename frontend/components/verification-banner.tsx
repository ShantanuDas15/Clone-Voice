"use client";

import { useAuth } from "@/components/auth-provider";
import { ResendVerification } from "@/components/resend-verification";

/** Persistent notice for signed-in users whose email isn't verified yet (blocks upload/synthesis server-side). */
export function VerificationBanner() {
  const { status, user } = useAuth();
  if (status !== "authenticated" || !user || user.email_verified_at) return null;
  return (
    <div className="sticky bottom-0 z-30 border-t border-border bg-warning px-4 py-2 text-center text-sm text-warning-foreground">
      Verify your email address ({user.email}) to upload voices and generate speech.{" "}
      <ResendVerification />
    </div>
  );
}
