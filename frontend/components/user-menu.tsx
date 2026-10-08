"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { NavLink } from "@/components/nav-link";
import { Button, buttonVariants } from "@/components/ui/button";

/** Header account controls: sign-in links, or the user's name and a sign-out button. */
export function UserMenu() {
  const { status, user, logout } = useAuth();
  const router = useRouter();

  // Every state is at least as tall as the 44 px sign-out button, and below `sm` the menu has
  // its own row (see app-shell), so the header never changes height when the session
  // resolves (CLS).
  if (status === "loading") {
    return (
      <div aria-hidden className="flex min-h-11 items-center">
        <div className="h-6 w-24 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if (status === "unauthenticated") {
    return (
      <div className="flex min-h-11 items-center gap-4 text-sm">
        <Link href="/login" className="underline-offset-4 hover:underline">
          Sign in
        </Link>
        <Link href="/signup" className={buttonVariants({ size: "sm" })}>
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm sm:gap-x-4">
      <NavLink href="/generate">Generate</NavLink>
      <NavLink href="/voices">Voices</NavLink>
      <NavLink href="/history">History</NavLink>
      <NavLink href="/account">Account</NavLink>
      <span className="hidden max-w-[10rem] truncate text-muted-foreground sm:inline">
        {user?.name}
      </span>
      <Button
        variant="secondary"
        size="sm"
        onClick={async () => {
          await logout();
          router.replace("/");
        }}
      >
        Sign out
      </Button>
    </div>
  );
}
