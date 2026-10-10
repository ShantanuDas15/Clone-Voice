import type { Metadata } from "next";

import { AuthCard } from "@/components/auth-card";
import { SignupForm } from "@/components/signup-form";

export const metadata: Metadata = { title: "Create account" };

export default function SignupPage() {
  return (
    <AuthCard
      title="Create your account"
      lead="Clone a voice you have the right to use in a few minutes."
    >
      <SignupForm />
    </AuthCard>
  );
}
