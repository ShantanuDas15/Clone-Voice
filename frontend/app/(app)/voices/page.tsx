import type { Metadata } from "next";

import "../../voices-experience.css";

import { PageHeader } from "@/components/ui/page-header";
import { VerifyEmailAlert } from "@/components/verify-email-alert";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceCount, VoiceProfileList } from "@/components/voice-profile-list";

export const metadata: Metadata = { title: "Voices" };

export default function VoicesPage() {
  return (
    <div>
      <PageHeader title="Voices">
        Create a voice from a sample, then manage the ones you have.
      </PageHeader>
      <VerifyEmailAlert />
      <UploadVoiceForm>
        <section aria-labelledby="my-voices" className="bx-card bx-shelf">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 id="my-voices" className="text-xl font-semibold">
              Your voices
            </h2>
            <VoiceCount />
          </div>
          <VoiceProfileList />
        </section>
      </UploadVoiceForm>
    </div>
  );
}
