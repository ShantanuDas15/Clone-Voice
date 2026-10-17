import type { Metadata } from "next";

import { VerifyEmailView } from "@/components/verify-email-view";

export const metadata: Metadata = { title: "Verify email" };

export default function Page() {
  return <VerifyEmailView />;
}
