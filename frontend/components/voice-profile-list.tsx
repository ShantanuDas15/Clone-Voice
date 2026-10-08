"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { useDeleteProfile, useProfiles } from "@/hooks/use-voice-profiles";
import type { VoiceProfile } from "@/lib/api/voice";
import { ApiError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

function StatusChip({ status }: { status: string }) {
  if (status === "ready") return <Badge tone="success">Ready</Badge>;
  if (status === "failed") return <Badge tone="notice">Failed</Badge>;
  return <Badge>Processing</Badge>;
}

/** Modal confirmation for deleting a voice; traps focus and closes on Escape or a scrim click. */
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

/** The user's voices with loading, empty, error and failed-row states, and confirmed deletion. */
export function VoiceProfileList() {
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
      <ul className="space-y-2">
        {data.map((p) => (
          <li
            key={p.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-3"
          >
            <div>
              <p className="font-medium">
                {p.name} <StatusChip status={p.status} />
              </p>
              <p className="text-sm text-muted-foreground">
                Created {formatDateTime(p.created_at)}
              </p>
              {p.status === "failed" && (
                <p className="text-sm">
                  This upload couldn&apos;t be processed. Delete it and try again.
                </p>
              )}
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConfirming(p)}
              disabled={remove.isPending && remove.variables === p.id}
              aria-label={`Delete ${p.name}`}
            >
              Delete
            </Button>
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
                toast.error(e instanceof ApiError ? e.message : "Couldn't delete that voice."),
              onSuccess: () => toast.success(`Deleted “${target.name}”.`),
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
