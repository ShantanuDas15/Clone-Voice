import type { ReactNode } from "react";

import { type PanelCopy, VoicePanel, VoiceStrip } from "@/components/voice-panel";

/**
 * The one frame for every account-entry page: a bordered panel with a title and a short lead.
 * With `panel` (sign in and sign up) it sits beside a voice panel from `lg` up, and under a thin
 * wave below that (UX plan §12.24); without it (forgot and reset password) it is the plain card.
 */
export function AuthCard({
  title,
  lead,
  panel,
  children,
}: {
  title: string;
  lead?: string;
  panel?: PanelCopy;
  children: ReactNode;
}) {
  const card = (
    <section
      className={`mx-auto mt-2 w-full max-w-md rounded-lg border bg-surface p-6 sm:mt-8 sm:p-8 ${
        panel ? "border-primary/40" : "border-border"
      } ${panel ? "lg:mx-0 lg:mt-0 lg:self-center lg:justify-self-end" : ""}`}
    >
      {panel && <VoiceStrip />}
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {lead ? <p className="mt-2 text-sm text-muted-foreground">{lead}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  );
  if (!panel) return card;
  return (
    <div className="lg:grid lg:min-h-[34rem] lg:grid-cols-[11fr_9fr] lg:gap-14 lg:py-6">
      <VoicePanel copy={panel} />
      {card}
    </div>
  );
}
