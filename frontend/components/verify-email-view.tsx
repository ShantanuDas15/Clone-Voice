"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AuthCard } from "@/components/auth-card";
import { ResendVerification } from "@/components/resend-verification";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
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

  function verify(token: string) {
    setView("working");
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
  }

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setView("incomplete");
      return;
    }
    if (started.current) return; // Strict Mode double effect
    started.current = true;
    verify(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signedIn = status === "authenticated";
  // A link that cannot be used leaves one way forward: a fresh email (signed in) or signing in to
  // ask for one.
  const newLink = signedIn ? (
    <ResendVerification flush />
  ) : (
    <Link href="/login" className="underline">
      Sign in to request a new link
    </Link>
  );

  return (
    <AuthCard title={view === "verified" ? "Email verified" : "Verify email"}>
      {view === "error" ? (
        <div className="space-y-4">
          <Alert tone="danger">{message}</Alert>
          <Button
            variant="secondary"
            onClick={() => {
              const token = getToken();
              if (token) verify(token);
            }}
          >
            Try again
          </Button>
        </div>
      ) : (
        <div role="status" aria-live="polite" className="space-y-4">
          {view === "working" && <p>Verifying your email…</p>}
          {view === "verified" && (
            <>
              <p>Your email address is verified.</p>
              <Link
                href={signedIn ? "/generate" : "/login"}
                className={buttonVariants({ fullWidth: true })}
              >
                {signedIn ? "Start generating" : "Sign in"}
              </Link>
            </>
          )}
          {view === "incomplete" && (
            <>
              <p>
                This link looks incomplete. Open the link from your email again, or request a new
                one.
              </p>
              {newLink}
            </>
          )}
          {view === "invalid" && (
            <>
              <p>This link is invalid or has expired.</p>
              {newLink}
            </>
          )}
        </div>
      )}
    </AuthCard>
  );
}
