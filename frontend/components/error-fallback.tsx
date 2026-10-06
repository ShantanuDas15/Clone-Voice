"use client";

/** Shared fallback UI for route/root error boundaries. Never shows raw error text. */
export function ErrorFallback({ reset }: { reset: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="mt-2 text-muted-foreground">An unexpected error occurred. Please try again.</p>
      <button
        type="button"
        onClick={reset}
        className="mt-6 min-h-11 rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        Try again
      </button>
    </div>
  );
}
