"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import dynamic from "next/dynamic";
import { Toaster } from "sonner";

import { AuthProvider } from "@/components/auth-provider";
import { env } from "@/lib/env";
import { createQueryClient } from "@/lib/query";

// Loaded only when reporting is configured, so it adds nothing to the default bundle.
const WebVitals = dynamic(() => import("@/components/web-vitals").then((m) => m.WebVitals), {
  ssr: false,
});

/** Client-side providers: TanStack Query and the accessible toast region. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      {env.NEXT_PUBLIC_SENTRY_DSN ? <WebVitals /> : null}
      <AuthProvider>{children}</AuthProvider>
      <Toaster richColors closeButton />
    </QueryClientProvider>
  );
}
