import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth-card";
import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <AuthCard
      title="Sign in"
      lead="Welcome back. Sign in to your voices and history."
      panel={{
        headline: "Welcome back.",
        accent: "Your voices are waiting.",
        lead: "Pick up where you left off: your voices, your history, and anything you were about to say.",
      }}
    >
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthCard>
  );
}
