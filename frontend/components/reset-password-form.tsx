"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { TextField } from "@/components/form-fields";
import { Button } from "@/components/ui/button";
import { resetPassword } from "@/lib/api/auth";
import { useFragmentToken } from "@/lib/auth/fragment";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { clearSession } from "@/lib/auth/session";
import { ApiError } from "@/lib/errors";
import { type ResetValues, resetSchema } from "@/lib/validation/auth";
import { Alert } from "@/components/ui/alert";

type View = "checking" | "form" | "incomplete" | "invalid" | "done";

/** Reads the token from the URL fragment; success revokes all sessions, so local state is cleared. */
export function ResetPasswordForm() {
  const getToken = useFragmentToken();
  const [view, setView] = useState<View>("checking");
  const [token, setToken] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResetValues>({ resolver: zodResolver(resetSchema) });

  useEffect(() => {
    const t = getToken();
    setToken(t);
    setView(t ? "form" : "incomplete");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = handleSubmit(async ({ password }) => {
    if (inFlight.current || !token) return; // R4: a reset token is single-use
    inFlight.current = true;
    setFormError(null);
    try {
      await resetPassword({ token, newPassword: password });
      clearSession(); // the server revoked every session
      setView("done");
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 400) setView("invalid");
      else if (e.kind === "RATE_LIMITED") setFormError(rateLimitMessage(e));
      else setFormError(e.message);
    } finally {
      inFlight.current = false;
    }
  });

  if (view === "checking") return null;
  if (view === "incomplete" || view === "invalid") {
    return (
      <div role="alert" className="space-y-4">
        <p>
          {view === "incomplete"
            ? "This link looks incomplete. Open the link from your email again, or request a new one."
            : "This link is invalid or has expired."}
        </p>
        <Link href="/forgot-password" className="underline">
          Request a new link
        </Link>
      </div>
    );
  }
  if (view === "done") {
    return (
      <div role="status" className="space-y-4">
        <p>Your password has been changed. Sign in with your new password.</p>
        <Link href="/login" className="underline">
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        error={errors.password?.message}
        {...register("password")}
      />
      <TextField
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        error={errors.confirm?.message}
        {...register("confirm")}
      />
      {formError && <Alert tone="danger">{formError}</Alert>}
      <Button type="submit" disabled={isSubmitting} loading={isSubmitting} fullWidth>
        {isSubmitting ? "Saving…" : "Set new password"}
      </Button>
    </form>
  );
}
