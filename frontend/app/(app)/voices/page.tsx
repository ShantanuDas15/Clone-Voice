import type { Metadata } from "next";

import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";

export const metadata: Metadata = { title: "Voices" };

export default function VoicesPage() {
  return (
    <div className="space-y-10">
      <h1 className="text-2xl font-bold">Voices</h1>
      <section aria-labelledby="new-voice" className="max-w-xl">
        <h2 id="new-voice" className="mb-4 text-xl font-semibold">
          Create a voice
        </h2>
        <UploadVoiceForm />
      </section>
      <section aria-labelledby="my-voices" className="max-w-xl">
        <h2 id="my-voices" className="mb-4 text-xl font-semibold">
          Your voices
        </h2>
        <VoiceProfileList />
      </section>
    </div>
  );
}
