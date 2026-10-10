import type { Metadata } from "next";

import { AuthCard } from "@/components/auth-card";
import { VerifyEmailView } from "@/components/verify-email-view";

export const metadata: Metadata = { title: "Verify email" };

export default function Page() {
  return (
    <AuthCard title="Verify email">
      <VerifyEmailView />
    </AuthCard>
  );
}
