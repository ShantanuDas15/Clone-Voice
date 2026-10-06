import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <section className="mx-auto max-w-sm">
      <h1 className="mb-6 text-2xl font-bold">Sign in</h1>
      <Suspense>
        <LoginForm />
      </Suspense>
    </section>
  );
}
