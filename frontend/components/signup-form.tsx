"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "@/components/auth-provider";
import { TextField } from "@/components/form-fields";
import { Button } from "@/components/ui/button";
import { GoogleButton } from "@/components/google-button";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { type SignupValues, signupSchema } from "@/lib/validation/auth";
import { Alert } from "@/components/ui/alert";

export function SignupForm() {
  const { signup, status } = useAuth();
  const router = useRouter();
  const inFlight = useRef(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [emailTaken, setEmailTaken] = useState(false);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<SignupValues>({ resolver: zodResolver(signupSchema) });

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  const onSubmit = handleSubmit(async (values) => {
    if (inFlight.current) return; // R4
    inFlight.current = true;
    setFormError(null);
    setEmailTaken(false);
    try {
      await signup({
        email: values.email.trim(),
        name: values.name.trim(),
        password: values.password,
      });
      router.replace("/dashboard");
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 409) {
        // Also the outcome of retrying after an ambiguous timeout: point to login.
        setEmailTaken(true);
        setError("email", { message: "An account with this email already exists." });
      } else if (e.kind === "RATE_LIMITED") setFormError(rateLimitMessage(e));
      else if (e.status === 422 && e.fieldErrors.length > 0) {
        let unmapped: string | null = null;
        for (const fe of e.fieldErrors) {
          if (fe.field === "email" || fe.field === "name" || fe.field === "password") {
            setError(fe.field, { message: fe.message });
          } else unmapped = fe.message;
        }
        setFormError(unmapped);
      } else setFormError(e.message);
    } finally {
      inFlight.current = false;
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <GoogleButton />
      <TextField
        label="Name"
        autoComplete="name"
        error={errors.name?.message}
        {...register("name")}
      />
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...register("email")}
      />
      <TextField
        label="Password"
        type="password"
        autoComplete="new-password"
        error={errors.password?.message}
        {...register("password")}
      />
      {emailTaken && (
        <p className="text-sm">
          <Link href="/login" className="underline">
            Sign in instead
          </Link>
        </p>
      )}
      {formError && <Alert tone="danger">{formError}</Alert>}
      <Button type="submit" disabled={isSubmitting} loading={isSubmitting} fullWidth>
        {isSubmitting ? "Creating account…" : "Create account"}
      </Button>
      <p className="text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
