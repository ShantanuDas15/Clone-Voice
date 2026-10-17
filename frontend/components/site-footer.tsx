import Link from "next/link";

import { BRAND_NAME } from "@/lib/brand";

/** One compact row: brand and terms on the left, the AI-content notice on the right. */
export function SiteFooter() {
  return (
    <footer className="border-t border-border py-4 text-sm text-muted-foreground">
      <div className="mx-auto flex max-w-5xl flex-col gap-1 px-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <p className="flex items-center gap-3">
          <span className="font-medium text-foreground">{BRAND_NAME}</span>
          <Link href="/terms" className="-my-3 inline-flex min-h-11 items-center underline">
            Terms
          </Link>
        </p>
        <p>Generated voices are AI-synthesized. Use only voices you have consent to clone.</p>
      </div>
    </footer>
  );
}
