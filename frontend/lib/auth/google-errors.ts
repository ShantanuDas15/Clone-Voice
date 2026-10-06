/** Stable codes the backend appends to `/login?error=` (auth.py), plus one client-side code. */
export const GOOGLE_ERROR_MESSAGES = {
  google_failed: "Google sign-in didn't complete. Please try again.",
  google_no_email: "Google didn't share an email address with us, so we couldn't sign you in.",
  google_email_unverified:
    "Your Google email address isn't verified. Verify it with Google, then try again.",
  google_account_conflict:
    "This email already belongs to an account that can't be linked automatically. Sign in with your password instead.",
  session_unavailable:
    "Sign-in finished, but your browser didn't keep the session. Check that cookies are enabled for this site and try again.",
} as const;

export type GoogleErrorCode = keyof typeof GOOGLE_ERROR_MESSAGES;

const GENERIC = "Sign-in failed. Please try again.";

/** Map a `?error=` value to user copy; unknown or missing codes get generic text (or null if absent). */
export function googleErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return Object.hasOwn(GOOGLE_ERROR_MESSAGES, code)
    ? GOOGLE_ERROR_MESSAGES[code as GoogleErrorCode]
    : GENERIC;
}
