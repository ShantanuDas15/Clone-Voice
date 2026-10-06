import type { Metadata } from "next";
import Link from "next/link";

import { TextToSpeechForm } from "@/components/text-to-speech-form";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <section>
      <h1 className="text-2xl font-bold">Generate speech</h1>
      <p className="mb-6 mt-2 text-muted-foreground">
        Pick one of your voices and type what it should say. Need a new voice?{" "}
        <Link href="/profile" className="underline">
          Create one
        </Link>
        .
      </p>
      <TextToSpeechForm />
    </section>
  );
}
