"use client";

import { Button, buttonVariants } from "@/components/ui/button";

/**
 * Shared fallback UI for route/root error boundaries. Never shows raw error text, and always
 * offers a way out: try again, or leave for the app's main page. A plain link (full load) is used
 * on purpose: after a crash the router state cannot be trusted, and the global fallback has none.
 */
export function ErrorFallback({ reset }: { reset: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="mt-2 text-muted-foreground">An unexpected error occurred. Please try again.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Button onClick={reset}>Try again</Button>
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- see the comment above */}
        <a href="/generate" className={buttonVariants({ variant: "secondary" })}>
          Go to Generate
        </a>
      </div>
    </div>
  );
}
