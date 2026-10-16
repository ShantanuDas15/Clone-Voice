"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";

/** Landing-page calls to action: sign-up/sign-in for visitors, a way back into the app when signed in. */
export function HomeActions() {
  const { status } = useAuth();

  // A fixed-height placeholder while the session resolves, so the hero never shifts (CLS).
  if (status === "loading") {
    return <div aria-hidden className="mt-8 min-h-11" />;
  }

  return (
    <div className="mt-8 flex flex-wrap justify-center gap-3">
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
