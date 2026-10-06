import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";

// Dynamic rendering lets Next.js stamp the per-request CSP nonce (middleware.ts) on its scripts.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "CloneVoice", template: "%s · CloneVoice" },
  description: "Clone a voice from a short sample and synthesize speech from text.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
