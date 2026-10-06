import Link from "next/link";

export default function HomePage() {
  return (
    <section className="py-12">
      <h1 className="text-4xl font-bold tracking-tight">Clone a voice. Say anything.</h1>
      <p className="mt-4 max-w-prose text-muted-foreground">
        Upload a short speech sample, then turn any text into speech in that voice.
      </p>
      <Link
        href="/signup"
        className="mt-8 inline-flex min-h-11 items-center rounded bg-primary px-5 py-2 text-primary-foreground"
      >
        Get started
      </Link>
    </section>
  );
}
