import type { Metadata } from "next";
import Link from "next/link";

import { FirstRunChecklist } from "@/components/first-run-checklist";
import { TextToSpeechForm } from "@/components/text-to-speech-form";

export const metadata: Metadata = { title: "Generate speech" };

export default function GeneratePage({
  searchParams,
}: {
  searchParams: { voice?: string | string[] };
}) {
  const voice = typeof searchParams.voice === "string" ? searchParams.voice : undefined;
  return (
    <section>
      <h1 className="text-2xl font-bold">Generate speech</h1>
      <p className="mb-4 mt-2 text-muted-foreground">
        Pick one of your voices and type what it should say. Need a new voice?{" "}
        <Link href="/voices" className="underline">
          Create one
        </Link>
        .
      </p>
      <TextToSpeechForm initialVoiceId={voice} />
      <FirstRunChecklist />
    </section>
  );
}
