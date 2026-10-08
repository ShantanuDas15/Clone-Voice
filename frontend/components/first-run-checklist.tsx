"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { ResendVerification } from "@/components/resend-verification";
import { StepList } from "@/components/step-list";
import { buttonVariants } from "@/components/ui/button";
import { useProfiles } from "@/hooks/use-voice-profiles";
import { firstRun } from "@/lib/first-run";

/**
 * Shown on Generate until a verified email and a ready voice both exist: the path to a first
 * take, with the next action as the primary button. Renders nothing once it is complete.
 */
export function FirstRunChecklist() {
  const { status, user } = useAuth();
  const profiles = useProfiles();
  if (status !== "authenticated" || !user) return null;

  const verified = Boolean(user.email_verified_at);
  // Wait for the list before judging the voice step, so a returning user never sees a flash.
  if (verified && profiles.isPending) return null;
  const hasReadyVoice = (profiles.data ?? []).some((p) => p.status === "ready");
  const hasFailed = (profiles.data ?? []).some((p) => p.status === "failed");
  const state = firstRun({ emailVerified: verified, hasReadyVoice });
  if (!state.blocker) return null;

  return (
    <section
      aria-labelledby="first-run-title"
      className="mb-6 max-w-xl rounded border border-border bg-muted p-4"
    >
      <h2 id="first-run-title" className="mb-3 text-lg font-semibold">
        Get your first result
      </h2>
      <StepList
        label="First steps"
        steps={[
          {
            id: "verify",
            title: "Verify your email",
            status: state.verify,
            detail: (
              <>
                Verify your email address ({user.email}) to upload voices and generate speech.{" "}
                <ResendVerification />
              </>
            ),
          },
          {
            id: "voice",
            title: "Create a voice",
            status: state.voice,
            detail: (
              <>
                {hasFailed
                  ? "Your last upload couldn't be processed. Add a new sample."
                  : "Upload or record 10–30 seconds of a voice you have the right to use."}{" "}
                {state.voice === "current" && (
                  <Link href="/voices" className={buttonVariants({ className: "mt-2" })}>
                    Create a voice
                  </Link>
                )}
              </>
            ),
          },
          { id: "generate", title: "Generate speech", status: state.generate },
        ]}
      />
    </section>
  );
}
