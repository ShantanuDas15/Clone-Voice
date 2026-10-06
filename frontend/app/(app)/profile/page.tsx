import type { Metadata } from "next";

import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";

export const metadata: Metadata = { title: "Your voices" };

export default function ProfilePage() {
  return (
    <div className="space-y-10">
      <section aria-labelledby="new-voice" className="max-w-xl">
        <h1 id="new-voice" className="mb-4 text-2xl font-bold">
          Create a voice
        </h1>
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
