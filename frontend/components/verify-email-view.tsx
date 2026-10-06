"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ResendVerification } from "@/components/resend-verification";
import { verifyEmail } from "@/lib/api/auth";
import { useFragmentToken } from "@/lib/auth/fragment";
import { ApiError } from "@/lib/errors";

type View = "working" | "verified" | "incomplete" | "invalid" | "error";

/** Consumes the emailed token from the URL fragment and confirms the address. */
export function VerifyEmailView() {
  const [view, setView] = useState<View>("working");
  const [message, setMessage] = useState<string>("");
  const { status, refreshUser } = useAuth();
  const getToken = useFragmentToken();
  const started = useRef(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setView("incomplete");
      return;
    }
    if (started.current) return; // Strict Mode double effect
    started.current = true;
    verifyEmail(token)
      .then(() => {
        setView("verified");
        void refreshUser(); // no-op when signed out (401 is silent)
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 400) setView("invalid");
        else {
          setView("error");
          setMessage(e instanceof ApiError ? e.message : "Something went wrong.");
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div role="status" aria-live="polite" className="space-y-4">
      {view === "working" && <p>Verifying your email…</p>}
      {view === "verified" && (
        <>
          <p>Your email address is verified.</p>
          <Link href={status === "authenticated" ? "/dashboard" : "/login"} className="underline">
            {status === "authenticated" ? "Go to dashboard" : "Sign in"}
          </Link>
        </>
      )}
      {view === "incomplete" && (
        <p>
          This link looks incomplete. Open the link from your email again, or request a new one.
        </p>
      )}
      {view === "invalid" && (
        <>
          <p>This link is invalid or has expired.</p>
          {status === "authenticated" ? (
            <ResendVerification />
          ) : (
            <Link href="/login" className="underline">
              Sign in to request a new link
            </Link>
          )}
        </>
      )}
      {view === "error" && <p role="alert">{message}</p>}
    </div>
  );
}
