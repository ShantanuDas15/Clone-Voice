"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";

/**
 * Landing-page calls to action: sign-up/sign-in for visitors, a way back into the app when signed in.
 * `closing` is the single link that ends the page. The sign-up action keeps its one label, "Create
 * account" (UX-13), wherever it appears.
 */
export function HomeActions({
  align = "center",
  closing = false,
}: {
  align?: "center" | "start";
  closing?: boolean;
}) {
  const { status } = useAuth();
  const spacing = closing ? "mt-6" : "mt-8";

  // A fixed-height placeholder while the session resolves, so the hero never shifts (CLS).
  if (status === "loading") {
    return <div aria-hidden className={`${spacing} min-h-11`} />;
  }

  const row = `hx-cta ${spacing} flex flex-wrap gap-3 ${align === "center" ? "justify-center" : "justify-start"}`;

  if (closing) {
    return (
      <div className={row}>
        {status === "authenticated" ? (
          <Link href="/voices" className={buttonVariants()}>
            Add a voice
          </Link>
        ) : (
          <Link href="/signup" className={buttonVariants()}>
            Create account
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className={row}>
      {status === "authenticated" ? (
        <>
          <Link href="/generate" className={buttonVariants()}>
            Go to Generate
          </Link>
          <Link href="/voices" className={buttonVariants({ variant: "secondary" })}>
            Your voices
          </Link>
        </>
      ) : (
        <>
          <Link href="/signup" className={buttonVariants()}>
            Create account
          </Link>
          <Link href="/login" className={buttonVariants({ variant: "secondary" })}>
            Sign in
          </Link>
        </>
      )}
    </div>
  );
}
