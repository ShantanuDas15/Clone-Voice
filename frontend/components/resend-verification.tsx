"use client";

import { useRef, useState } from "react";

import { resendVerification } from "@/lib/api/auth";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";

type State = { kind: "idle" } | { kind: "sent" } | { kind: "error"; message: string };

/** Sends a fresh verification email (5/hour per IP, so a 429 explains the wait). */
export function ResendVerification({ className }: { className?: string }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);

  async function onClick() {
    if (inFlight.current) return; // R4
    inFlight.current = true;
    setBusy(true);
    try {
      await resendVerification();
      setState({ kind: "sent" });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.kind === "RATE_LIMITED") setState({ kind: "error", message: rateLimitMessage(e) });
      else if (e.status === 401)
        setState({ kind: "error", message: "Please sign in again to resend the email." });
      else setState({ kind: "error", message: e.message });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <span className={className}>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="underline disabled:opacity-60"
      >
        {busy ? "Sending…" : "Resend verification email"}
      </button>
      <span role="status" aria-live="polite" className="ml-2">
        {state.kind === "sent" && "Email sent. Check your inbox."}
        {state.kind === "error" && state.message}
      </span>
    </span>
  );
}
