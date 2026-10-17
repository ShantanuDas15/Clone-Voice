"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { TextField } from "@/components/form-fields";
import { Button } from "@/components/ui/button";
import { useTerms } from "@/hooks/use-terms";
import { forgotPassword } from "@/lib/api/auth";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { describeLinkLifetime } from "@/lib/retention";
import { type ForgotValues, forgotSchema } from "@/lib/validation/auth";
import { Alert } from "@/components/ui/alert";

/** Neutral by design: the same confirmation shows whether or not the account exists. */
export function ForgotPasswordForm() {
  const lifetime = describeLinkLifetime(useTerms().data?.password_reset_expire_minutes);
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
          If an account exists for that email, we&apos;ve sent a link to set a new password.
          {lifetime && ` It expires in ${lifetime}.`}
        </p>
        <Link href="/login" className="underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        autoCapitalize="none"
        spellCheck={false}
        error={errors.email?.message}
        {...register("email")}
      />
      {formError && <Alert tone="danger">{formError}</Alert>}
      <Button type="submit" loading={isSubmitting} fullWidth>
        {isSubmitting ? "Sending…" : "Send reset link"}
      </Button>
    </form>
  );
}
