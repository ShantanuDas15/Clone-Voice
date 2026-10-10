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

// The product's real sequence (upload or record, then type, then play or download). No claim
// about quality, speed or languages is made here.
const STEPS = [
  {
    title: "Add a sample",
    body: "Upload or record 10 to 30 seconds of a voice you have the right to use.",
  },
  { title: "Type your text", body: "Choose the voice and write what it should say." },
  { title: "Play or download", body: "Listen right away, replay it later from your history." },
] as const;

export default function HomePage() {
  return (
    <>
      <section className="rounded-lg bg-muted px-6 py-14 text-center sm:py-20">
        <h1 className="mx-auto max-w-2xl text-[2rem] font-semibold leading-[2.375rem] tracking-tight sm:text-5xl sm:leading-[3.25rem]">
          Clone a voice. Say anything.
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground">
          Upload or record 10 to 30 seconds of a voice you have the right to use, then turn any text
          into speech in that voice.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/signup" className={buttonVariants()}>
            Create account
          </Link>
          <Link href="/login" className={buttonVariants({ variant: "secondary" })}>
            Sign in
          </Link>
        </div>
      </section>

      <section aria-labelledby="how" className="mt-16">
        <h2 id="how" className="text-xl font-semibold tracking-tight">
          How it works
        </h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <div key={s.title} className="rounded-lg border border-border bg-surface p-5">
              <p className="text-sm font-medium text-primary">Step {i + 1}</p>
              <h3 className="mt-2 font-semibold">{s.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="start" className="mt-16">
        <h2 id="start" className="text-xl font-semibold tracking-tight">
          Before you start
        </h2>
        <ul className="mt-5 divide-y divide-border rounded-lg border border-border bg-surface">
          {PROMISES.map((p) => (
            <li key={p} className="px-5 py-3.5">
              {p}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
