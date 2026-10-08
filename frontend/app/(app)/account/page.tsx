import type { Metadata } from "next";

import { AccountSection } from "@/components/account-section";

export const metadata: Metadata = { title: "Account" };

export default function AccountPage() {
  return (
    <section className="max-w-xl">
      <h1 className="mb-4 text-2xl font-bold">Account</h1>
      <AccountSection />
    </section>
  );
}
