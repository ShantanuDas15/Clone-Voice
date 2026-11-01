import type { Metadata } from "next";
import Link from "next/link";

import { FirstRunChecklist } from "@/components/first-run-checklist";
import { PageHeader } from "@/components/ui/page-header";
import { TextToSpeechForm } from "@/components/text-to-speech-form";

export const metadata: Metadata = { title: "Generate speech" };

export default async function GeneratePage({
  searchParams,
}: {
  searchParams: Promise<{ voice?: string | string[] }>;
}) {
  const { voice: voiceParam } = await searchParams;
  const voice = typeof voiceParam === "string" ? voiceParam : undefined;
  return (
    <section>
      <PageHeader title="Generate speech">
        Pick one of your voices and type what it should say. Need a new voice?{" "}
        <Link href="/voices" className="underline">
          Create one
        </Link>
        .
      </PageHeader>
      <TextToSpeechForm initialVoiceId={voice} />
      <FirstRunChecklist />
    </section>
  );
}
