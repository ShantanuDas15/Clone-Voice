"use client";

import Link from "next/link";
import { useState } from "react";
import { notify } from "@/lib/toast";

import { useListMotion } from "@/hooks/use-list-motion";
import { useDeleteProfile, useProfiles } from "@/hooks/use-voice-profiles";
import type { VoiceProfile, VoiceSample } from "@/lib/api/voice";
import { ApiError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { voiceAdvice } from "@/lib/voice-advice";
import { QUALITY_LABEL, overallQuality } from "@/lib/voice-quality";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { VoiceGlyph } from "@/components/voice-glyph";
import { ProfileClips } from "@/components/profile-clips";

function StatusChip({ status }: { status: string }) {
  if (status === "ready") return <Badge tone="success">Ready</Badge>;
  if (status === "failed") return <Badge tone="notice">Failed</Badge>;
  return <Badge>Processing</Badge>;
}

/** Modal confirmation for deleting a voice; traps focus and closes on Escape or a scrim click. */
/** How many clips a voice is made from and how good the worst of them is, so it reads at a glance. */
function VoiceSummary({ samples }: { samples: readonly VoiceSample[] }) {
  const quality = overallQuality(samples);
  if (samples.length === 0 && quality === null) return null;
  return (
    <>
      {samples.length > 0 && (
        <>
          <span aria-hidden>·</span>
          <span>{samples.length === 1 ? "1 clip" : `${samples.length} clips`}</span>
        </>
      )}
      {quality && (
        <Badge tone={quality === "good" ? "neutral" : "notice"}>{QUALITY_LABEL[quality]}</Badge>
      )}
    </>
  );
}

function DeleteDialog({
  profile,
  onCancel,
  onConfirm,
}: {
  profile: VoiceProfile;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog titleId="del-title" onClose={onCancel}>
      <h3 id="del-title" className="text-lg font-semibold">
        Delete “{profile.name}”?
      </h3>
      <p className="text-sm">
        This also permanently removes every audio clip generated with this voice. It can&apos;t be
        undone.
      </p>
      <div className="flex gap-2">
        <Button variant="danger" autoFocus onClick={onConfirm}>
          Delete voice
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Dialog>
  );
}

/** "3 voices" beside the shelf heading; nothing until the list has loaded and is not empty. */
export function VoiceCount() {
  const { data } = useProfiles();
  if (!data || data.length === 0) return null;
  return (
    <span data-testid="voice-count" className="bx-count">
      {data.length === 1 ? "1 voice" : `${data.length} voices`}
    </span>
  );
}

/** The user's voices with loading, empty, error and failed-row states, and confirmed deletion. */
export function VoiceProfileList() {
  const listRef = useListMotion();
  const { data, isPending, isError, refetch } = useProfiles();
  const remove = useDeleteProfile();
  const [confirming, setConfirming] = useState<VoiceProfile | null>(null);

  if (isPending) {
    return (
      <ul aria-busy="true" aria-label="Loading voices" className="space-y-2">
        {[0, 1].map((i) => (
          <li key={i} className="h-16 animate-pulse rounded bg-muted" />
        ))}
      </ul>
    );
  }
  if (isError) {
    return (
      <div role="alert" className="space-y-2">
        <p>We couldn&apos;t load your voices.</p>
        <Button variant="secondary" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-muted-foreground">You haven&apos;t created a voice yet.</p>
        <Button onClick={() => document.getElementById("voice-name")?.focus()}>
          Create a voice
        </Button>
      </div>
    );
  }

  return (
    <>
      <ul ref={listRef} className="bx-shelf-list">
        {data.map((p) => (
          <li key={p.id} className="bx-vcard">
            <div className="bx-vtop">
              <p className="font-medium">
                {p.name} <StatusChip status={p.status} />
              </p>
              <p className="bx-vmeta flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                <span>Created {formatDateTime(p.created_at)}</span>
                {p.status === "ready" && <VoiceSummary samples={p.samples ?? []} />}
              </p>
              {p.status === "ready" && voiceAdvice(p.samples ?? []) && (
                <p className="text-sm">{voiceAdvice(p.samples ?? [])} Open Clips for tips.</p>
              )}
              {p.status === "failed" && (
                <p className="text-sm">
                  This upload couldn&apos;t be processed. Delete it and try again.
                </p>
              )}
            </div>
            {p.status === "ready" && <VoiceGlyph id={p.id} bars={64} className="bx-glyph" />}
            <div className="bx-vact flex gap-2">
              {p.status === "ready" && (
                <Link
                  href={`/generate?voice=${encodeURIComponent(p.id)}`}
                  className={buttonVariants({ size: "sm" })}
                  aria-label={`Generate speech with ${p.name}`}
                >
                  Generate
                </Link>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setConfirming(p)}
                disabled={remove.isPending && remove.variables === p.id}
                aria-label={`Delete ${p.name}`}
              >
                Delete
              </Button>
            </div>
            {p.status === "ready" && <ProfileClips profile={p} />}
          </li>
        ))}
      </ul>

      {confirming && (
        <DeleteDialog
          profile={confirming}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const target = confirming;
            setConfirming(null);
            remove.mutate(target.id, {
              onError: (e) =>
                notify.error(e instanceof ApiError ? e.message : "Couldn't delete that voice."),
              onSuccess: () => notify.success(`Deleted “${target.name}”.`),
            });
          }}
        />
      )}
      <p className="mt-4 text-sm text-muted-foreground">
        Ready to hear it?{" "}
        <Link href="/generate" className="underline">
          Generate speech
        </Link>
      </p>
    </>
  );
}
