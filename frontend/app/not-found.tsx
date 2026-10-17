import type { Metadata } from "next";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

/** Themed 404 inside the app shell, with a way back (the stock Next.js page has neither). */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-muted-foreground">
        That address doesn&apos;t match a page here. It may have moved, or the link may be mistyped.
      </p>
      <div className="mt-6 flex justify-center">
        <Link href="/" className={buttonVariants()}>
          Go to the home page
        </Link>
      </div>
    </div>
  );
}
