import type { Metadata } from "next";

import { GoogleCallback } from "@/components/google-callback";

export const metadata: Metadata = { title: "Signing you in" };

export default function Page() {
  return (
    <section className="mx-auto max-w-sm">
      <h1 className="mb-6 text-2xl font-bold">Signing you in</h1>
      <GoogleCallback />
    </section>
  );
}
