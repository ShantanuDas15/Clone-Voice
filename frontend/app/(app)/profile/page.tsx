import type { Metadata } from "next";

import { AccountSection } from "@/components/account-section";
import { HistoryList } from "@/components/history-list";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";

export const metadata: Metadata = { title: "Your account" };

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
      <section aria-labelledby="history" className="max-w-xl">
        <h2 id="history" className="mb-4 text-xl font-semibold">
          History
        </h2>
        <HistoryList />
      </section>
      <section aria-labelledby="account" className="max-w-xl">
        <h2 id="account" className="mb-4 text-xl font-semibold">
          Account
        </h2>
        <AccountSection />
      </section>
    </div>
  );
}
