"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Toaster } from "sonner";

import { AuthProvider } from "@/components/auth-provider";
import { createQueryClient } from "@/lib/query";

/** Client-side providers: TanStack Query and the accessible toast region. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
      <Toaster richColors closeButton />
    </QueryClientProvider>
  );
}
