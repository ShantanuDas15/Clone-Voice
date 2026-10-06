import type { Metadata } from "next";

import { SignupForm } from "@/components/signup-form";

export const metadata: Metadata = { title: "Create account" };

export default function SignupPage() {
  return (
    <section className="mx-auto max-w-sm">
      <h1 className="mb-6 text-2xl font-bold">Create your account</h1>
      <SignupForm />
    </section>
  );
}
