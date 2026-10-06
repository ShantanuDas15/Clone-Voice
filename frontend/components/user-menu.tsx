"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

/** Header account controls: sign-in links, or the user's name and a sign-out button. */
export function UserMenu() {
  const { status, user, logout } = useAuth();
  const router = useRouter();

  if (status === "loading")
    return <div aria-hidden className="h-6 w-24 animate-pulse rounded bg-muted" />;

  if (status === "unauthenticated") {
    return (
      <div className="flex items-center gap-4 text-sm">
        <Link href="/login" className="underline-offset-4 hover:underline">
          Sign in
        </Link>
        <Link href="/signup" className="rounded bg-primary px-3 py-1.5 text-primary-foreground">
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4 text-sm">
      <Link href="/dashboard" className="underline-offset-4 hover:underline">
        Dashboard
      </Link>
      <Link href="/profile" className="underline-offset-4 hover:underline">
        Voices
      </Link>
      <span className="text-muted-foreground">{user?.name}</span>
      <button
        type="button"
        className="min-h-9 rounded border border-border px-3"
        onClick={async () => {
          await logout();
          router.replace("/");
        }}
      >
        Sign out
      </button>
    </div>
  );
}
