import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth-card";
import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <AuthCard title="Sign in" lead="Welcome back. Sign in to your voices and history.">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthCard>
  );
}
