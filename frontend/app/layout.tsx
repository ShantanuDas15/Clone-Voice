import type { Metadata } from "next";
import localFont from "next/font/local";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

import "./globals.css";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";
import { THEME_COOKIE, parseTheme, themeAttribute } from "@/lib/theme";
import { BRAND_NAME } from "@/lib/brand";

// Self-hosted (no third-party request, so the CSP's `font-src 'self'` holds). Sans carries the UI;
// mono is for times and counters, where tabular digits keep numbers from jittering. Mono loads only
// when a page uses it.
const sans = localFont({
  src: [
    { path: "./fonts/ibm-plex-sans-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-sans-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ibm-plex-sans-latin-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-sans",
  display: "swap",
});
const mono = localFont({
  src: [{ path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400", style: "normal" }],
  variable: "--font-mono",
  display: "swap",
  preload: false,
});

// Dynamic rendering lets Next.js stamp the per-request CSP nonce (middleware.ts) on its scripts.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: BRAND_NAME, template: `%s · ${BRAND_NAME}` },
  description: "Clone a voice from a short sample and synthesize speech from text.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // Read on the server so an explicit theme is on <html> in the first byte (no flash).
  const theme = parseTheme(cookies().get(THEME_COOKIE)?.value);
  return (
    <html
      lang="en"
      data-theme={themeAttribute(theme)}
      className={`${sans.variable} ${mono.variable}`}
    >
      <body>
        <Providers>
          <AppShell theme={theme}>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
