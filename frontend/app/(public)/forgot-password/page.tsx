import type { Metadata } from "next";

import { AuthCard } from "@/components/auth-card";
import { ForgotPasswordForm } from "@/components/forgot-password-form";

export const metadata: Metadata = { title: "Reset your password" };

export default function Page() {
  return (
    <AuthCard
      title="Reset your password"
      lead="Enter your email and we will send you a link to choose a new one."
    >
      <ForgotPasswordForm />
    </AuthCard>
  );
}
