"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "@/components/auth-provider";
import { PasswordField, TextField } from "@/components/form-fields";
import { OrDivider } from "@/components/or-divider";
import { Button } from "@/components/ui/button";
import { GoogleButton } from "@/components/google-button";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { PASSWORD_MAX, PASSWORD_MIN, type SignupValues, signupSchema } from "@/lib/validation/auth";
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
    if (status === "authenticated") router.replace("/generate");
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
      router.replace("/generate");
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
      <OrDivider>or use email</OrDivider>
      <TextField
        label="Name"
        autoComplete="name"
        autoCapitalize="words"
        error={errors.name?.message}
        {...register("name")}
      />
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        autoCapitalize="none"
        spellCheck={false}
        error={errors.email?.message}
        {...register("email")}
      />
      <PasswordField
        label="Password"
        hint={`${PASSWORD_MIN} to ${PASSWORD_MAX} characters`}
        autoComplete="new-password"
        error={errors.password?.message}
        {...register("password")}
      />
      {emailTaken && (
        <p className="text-sm">
          <Link href="/login" className="inline-flex min-h-11 items-center underline">
            Sign in instead
          </Link>
        </p>
      )}
      {formError && <Alert tone="danger">{formError}</Alert>}
      <p className="text-sm text-muted-foreground">
        We&apos;ll email you a link to verify your address. By creating an account you agree to the{" "}
        <Link href="/terms" className="underline">
          terms of use
        </Link>
        .
      </p>
      <Button type="submit" loading={isSubmitting} fullWidth>
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
