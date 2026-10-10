import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { TERMS_SECTIONS, TERMS_STATUS, TERMS_VERSION } from "@/lib/terms-content";

// A draft must not be indexed; it is not linked from anywhere until the backend's TERMS_URL is set.
export const metadata: Metadata =
  TERMS_STATUS === "draft"
    ? { title: "Terms of use", robots: { index: false, follow: false } }
    : { title: "Terms of use" };

export default function TermsPage() {
  return (
    <article className="max-w-prose space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Terms of use</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Version <span className="font-mono tabular-nums">{TERMS_VERSION}</span>
        </p>
      </header>
      {TERMS_STATUS === "draft" && (
        <Alert>These terms are a draft and are being finalised. They may change.</Alert>
      )}
      {TERMS_SECTIONS.map((s, i) => (
        <section key={s.heading} aria-labelledby={`terms-${i}`}>
          <h2 id={`terms-${i}`} className="text-xl font-semibold">
            {s.heading}
          </h2>
          <p className="mt-1">{s.body}</p>
        </section>
      ))}
    </article>
  );
}
