import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/page-header";
import { AccountSection } from "@/components/account-section";

export const metadata: Metadata = { title: "Account" };

export default function AccountPage() {
  return (
    <section className="max-w-xl">
      <PageHeader title="Account">Your details and account controls.</PageHeader>
      <AccountSection />
    </section>
  );
}
