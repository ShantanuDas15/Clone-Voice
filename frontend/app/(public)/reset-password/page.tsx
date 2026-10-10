import type { Metadata } from "next";

import { AuthCard } from "@/components/auth-card";
import { ResetPasswordForm } from "@/components/reset-password-form";

export const metadata: Metadata = { title: "Choose a new password" };

export default function Page() {
  return (
    <AuthCard title="Choose a new password">
      <ResetPasswordForm />
    </AuthCard>
  );
}
