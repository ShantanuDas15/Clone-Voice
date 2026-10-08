"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "@/components/auth-provider";
import { TextField } from "@/components/form-fields";
import { Button } from "@/components/ui/button";
import { GoogleButton } from "@/components/google-button";
import { googleErrorMessage } from "@/lib/auth/google-errors";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { sanitizeNext } from "@/lib/auth/next-path";
import { ApiError } from "@/lib/errors";
import { type LoginValues, loginSchema } from "@/lib/validation/auth";
import { Alert } from "@/components/ui/alert";

export function LoginForm() {
  const { login, status } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = sanitizeNext(params.get("next"));
  const callbackError = googleErrorMessage(params.get("error"));
  const inFlight = useRef(false);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  const onSubmit = handleSubmit(async (values) => {
    if (inFlight.current) return; // R4: block Enter-key repeats.
    inFlight.current = true;
    setFormError(null);
    try {
      await login({ email: values.email.trim(), password: values.password });
      router.replace(next);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.kind === "RATE_LIMITED") setFormError(rateLimitMessage(e));
      // G-19: one generic message; never confirm whether the account exists.
      else if (e.status === 401) {
        setFormError(
          "Incorrect email or password. If you signed up with Google, use “Continue with Google” or reset your password.",
        );
      } else if (e.status === 0 || e.status >= 500) setFormError(e.message);
      else setFormError(e.message);
    } finally {
      inFlight.current = false;
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {callbackError && <Alert tone="danger">{callbackError}</Alert>}
      <GoogleButton />
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
        autoComplete="current-password"
        error={errors.password?.message}
        {...register("password")}
      />
      {formError && <Alert tone="danger">{formError}</Alert>}
      <Button type="submit" disabled={isSubmitting} loading={isSubmitting} fullWidth>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </Button>
      <p className="text-sm">
        <Link href="/forgot-password" className="underline">
          Forgot your password?
        </Link>
      </p>
      <p className="text-sm text-muted-foreground">
        New here?{" "}
        <Link href="/signup" className="underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
