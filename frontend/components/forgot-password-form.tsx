"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { TextField } from "@/components/form-fields";
import { forgotPassword } from "@/lib/api/auth";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { type ForgotValues, forgotSchema } from "@/lib/validation/auth";

/** Neutral by design: the same confirmation shows whether or not the account exists. */
export function ForgotPasswordForm() {
  const inFlight = useRef(false);
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ForgotValues>({ resolver: zodResolver(forgotSchema) });

  const onSubmit = handleSubmit(async ({ email }) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setFormError(null);
    try {
      await forgotPassword(email.trim());
      setDone(true);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      setFormError(e.kind === "RATE_LIMITED" ? rateLimitMessage(e) : e.message);
    } finally {
      inFlight.current = false;
    }
  });

  if (done) {
    return (
      <div role="status" className="space-y-4">
        <p>
          If an account exists for that email, we&apos;ve sent a link to set a new password. It
          expires in 30 minutes.
        </p>
        <Link href="/login" className="underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Enter your email and we&apos;ll send a link to reset your password, or to set one if you
        signed up with Google.
      </p>
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...register("email")}
      />
      {formError && (
        <p role="alert" className="text-sm text-danger">
          {formError}
        </p>
      )}
      <button
        type="submit"
        disabled={isSubmitting}
        className="min-h-11 w-full rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-60"
      >
        {isSubmitting ? "Sending…" : "Send reset link"}
      </button>
    </form>
  );
}
