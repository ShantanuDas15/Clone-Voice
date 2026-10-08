import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function HomePage() {
  return (
    <section className="py-12">
      <h1 className="text-4xl font-bold tracking-tight">Clone a voice. Say anything.</h1>
      <p className="mt-4 max-w-prose text-muted-foreground">
        Upload a short speech sample, then turn any text into speech in that voice.
      </p>
      <Link href="/signup" className={buttonVariants({ className: "mt-8" })}>
        Get started
      </Link>
    </section>
  );
}
