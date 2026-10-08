import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

// Each statement is true by construction and cites its source (UX plan §11.3): consent is
// required at upload (backend/api/voice.py), deleting a voice erases everything made with it
// (backend/services/erasure.py), and the app labels generated speech (footer, result heading).
// No retention figure is published here: it is a server setting, not a promise the page controls.
const PROMISES = [
  "You must confirm you have the right to use a voice before you can clone it.",
  "Delete a voice and everything made with it is erased.",
  "Generated speech is labelled as AI-generated in the app.",
] as const;

export default function HomePage() {
  return (
    <section className="py-12">
      <h1 className="text-[2rem] font-bold leading-[2.375rem] tracking-tight sm:text-[2.75rem] sm:leading-[3rem]">
        Clone a voice. Say anything.
      </h1>
      <p className="mt-4 max-w-prose text-lg text-muted-foreground">
        Upload or record 10 to 30 seconds of a voice you have the right to use, then turn any text
        into speech in that voice.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/signup" className={buttonVariants()}>
          Create account
        </Link>
        <Link href="/login" className={buttonVariants({ variant: "secondary" })}>
          Sign in
        </Link>
      </div>
      <h2 className="mt-14 text-xl font-semibold">Before you start</h2>
      <ul className="mt-3 max-w-prose divide-y divide-border border-y border-border">
        {PROMISES.map((p) => (
          <li key={p} className="py-3">
            {p}
          </li>
        ))}
      </ul>
    </section>
  );
}
