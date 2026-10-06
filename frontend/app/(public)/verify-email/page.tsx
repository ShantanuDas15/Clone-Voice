import type { Metadata } from "next";

import { VerifyEmailView } from "@/components/verify-email-view";

export const metadata: Metadata = { title: "Verify email" };

export default function Page() {
  return (
    <section className="mx-auto max-w-sm">
      <h1 className="mb-6 text-2xl font-bold">Verify email</h1>
      <VerifyEmailView />
    </section>
  );
}
