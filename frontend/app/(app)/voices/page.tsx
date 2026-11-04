import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/page-header";
import { VerifyEmailAlert } from "@/components/verify-email-alert";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";

export const metadata: Metadata = { title: "Voices" };

export default function VoicesPage() {
  return (
    <div>
      <PageHeader title="Voices">
        Create a voice from a sample, then manage the ones you have.
      </PageHeader>
      <VerifyEmailAlert />
      <UploadVoiceForm />
      <section aria-labelledby="my-voices" className="mt-12 max-w-3xl">
        <h2 id="my-voices" className="mb-4 text-xl font-semibold">
          Your voices
        </h2>
        <VoiceProfileList />
      </section>
    </div>
  );
}
