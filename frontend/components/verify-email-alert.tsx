"use client";

import { useAuth } from "@/components/auth-provider";
import { ResendVerification } from "@/components/resend-verification";

/**
 * The one place the unverified-email gate is explained. It sits inline at the top of the pages
 * that need a verified address (Generate, Voices) and renders nothing once verified; the server
 * still enforces the gate.
 */
export function VerifyEmailAlert() {
  const { status, user } = useAuth();
  if (status !== "authenticated" || !user || user.email_verified_at) return null;
  return (
    <div
      role="status"
      className="mb-6 max-w-xl rounded border border-border bg-warning p-3 text-sm text-warning-foreground"
    >
      Verify your email address ({user.email}) to upload voices and generate speech.{" "}
      <ResendVerification />
    </div>
  );
}
